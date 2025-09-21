import os
import configparser
import asf_search as asf
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import logging
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
import rasterio
from rasterio.merge import merge
from rasterio.crs import CRS
import numpy as np
from shapely.geometry import box, Point
from shapely.wkt import loads
from shapely.geometry import Polygon
import geopandas as gpd
import fiona

# Set CMR timeout to 60 seconds
asf.constants.INTERNAL.CMR_TIMEOUT = 60

# Setup logging
def setup_logging(log_file):
    log_dir = os.path.dirname(log_file)
    os.makedirs(log_dir, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - Line %(lineno)d - %(message)s',
                        handlers=[logging.FileHandler(log_file), logging.StreamHandler()])
    return logging.getLogger(__name__)

logger = None

# Global config variables
USERNAME = ''
PASSWORD = ''
OUTPUT_DIR = ''
ORBIT_DIR = ''
DEM_DIR = ''
DEM_FILE = ''

def parse_config(config_path='config_sentinel_download_asf.txt'):
    global logger, USERNAME, PASSWORD, OUTPUT_DIR, ORBIT_DIR, DEM_DIR, DEM_FILE
    config = configparser.ConfigParser()
    config.read(config_path)
    
    # Credentials
    USERNAME = config['Credentials']['username']
    PASSWORD = config['Credentials']['password']
    
    # General
    start_date = config['General']['start_date']
    end_date = config['General']['end_date']
    platform = config['General']['platform']
    orbit_direction = config['General']['orbit_direction']
    polarization = config['General']['polarization']
    
    # Region
    region_type = config['Region']['region_type']
    region_folder = config['Region']['region_folder']
    region_wkt = None
    
    if region_type == 'bounding_box':
        bbox_coords = config['Region'].get('bbox_coordinates', '').strip()
        if not bbox_coords:
            raise ValueError("bbox_coordinates must be provided for region_type 'bounding_box'")
        lon_min, lat_min, lon_max, lat_max = map(float, bbox_coords.split(','))
        region_wkt = f"POLYGON(({lon_min} {lat_min}, {lon_max} {lat_min}, {lon_max} {lat_max}, {lon_min} {lat_max}, {lon_min} {lat_min}))"
        bbox_coordinates = f"{lon_min},{lat_min},{lon_max},{lat_max}"
    
    elif region_type == 'point_buffer':
        point_buffer = config['Region'].get('point_buffer', '').strip()
        if not point_buffer:
            raise ValueError("point_buffer must be provided for region_type 'point_buffer'")
        center_lon, center_lat, radius_km = map(float, point_buffer.split(','))
        point = Point(center_lon, center_lat)
        # Convert radius from km to degrees (approximate, assuming 1 degree ~ 111 km)
        radius_deg = radius_km / 111.0
        buffered_geom = point.buffer(radius_deg)
        region_wkt = buffered_geom.wkt
        bbox_coordinates = f"{buffered_geom.bounds[0]},{buffered_geom.bounds[1]},{buffered_geom.bounds[2]},{buffered_geom.bounds[3]}"
    
    elif region_type in ['shapefile', 'geojson', 'kml', 'kmz']:
        file_key = region_type  # shapefile, geojson, kml, or kmz
        file_path = config['Region'].get(file_key, '').strip()
        if not file_path:
            raise ValueError(f"{file_key} must be provided for region_type '{region_type}'")
        full_file_path = os.path.join(region_folder, file_path)
        if not os.path.exists(full_file_path):
            raise FileNotFoundError(f"{region_type} file not found: {full_file_path}")
        
        try:
            gdf = gpd.read_file(full_file_path)
            if gdf.empty:
                raise ValueError(f"No valid geometries found in {full_file_path}")
            # Assume the first geometry or union of all geometries
            geometry = gdf.geometry.unary_union
            region_wkt = geometry.wkt
            bbox_coordinates = f"{geometry.bounds[0]},{geometry.bounds[1]},{geometry.bounds[2]},{geometry.bounds[3]}"
        except Exception as e:
            raise ValueError(f"Error reading {region_type} file {full_file_path}: {str(e)}")
    
    else:
        raise ValueError(f"Unsupported region_type: {region_type}")
    
    # Processing
    min_coverage = int(config['Processing']['min_coverage'])
    min_images = int(config['Processing']['min_images'])
    batch_size = int(config['Processing']['batch_size'])
    num_threads = int(config['Processing']['num_threads'])
    
    # Output
    OUTPUT_DIR = config['Output']['output_dir']
    ORBIT_DIR = config['Output']['orbit_dir']
    DEM_FILE = config['Output']['dem_file']
    DEM_DIR = os.path.dirname(DEM_FILE)
    prefer_orbit_type = config['Output']['prefer_orbit_type']
    download_dem = config['Output'].getboolean('download_dem')
    continue_without_dem = config['Output'].getboolean('continue_without_dem')
    dem_resolution = config['Output']['dem_resolution']
    
    # Selection
    selected_path = config['Selection']['selected_path']
    selected_frame = config['Selection']['selected_frame']
    
    # Log file
    log_file = config['Output']['log_file']
    logger = setup_logging(log_file)
    
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(ORBIT_DIR, exist_ok=True)
    os.makedirs(DEM_DIR, exist_ok=True)
    
    return {
        'start_date': datetime.strptime(start_date, '%Y-%m-%d'),
        'end_date': datetime.strptime(end_date, '%Y-%m-%d'),
        'platform': platform,
        'orbit_direction': orbit_direction,
        'polarization': polarization,
        'region_wkt': region_wkt,
        'min_coverage': min_coverage,
        'min_images': min_images,
        'batch_size': batch_size,
        'num_threads': num_threads,
        'selected_path': selected_path if selected_path else None,
        'selected_frame': selected_frame if selected_frame else None,
        'download_dem': download_dem,
        'continue_without_dem': continue_without_dem,
        'dem_resolution': dem_resolution,
        'bbox_coordinates': bbox_coordinates,
        'prefer_orbit_type': prefer_orbit_type
    }

def search_slc_images(config):
    logger.info(f"Searching date range: {config['start_date']} to {config['end_date']}")
    logger.info(f"Searching for platform: {config['platform']}")
    logger.info(f"Selected path: {config['selected_path'] if config['selected_path'] else 'All paths'}")
    logger.info(f"Selected frame: {config['selected_frame'] if config['selected_frame'] else 'All frames'}")
    
    # ASF search parameters
    params = {
        'platform': config['platform'] if config['platform'] != 'both' else ['Sentinel-1A', 'Sentinel-1B'],
        'processingLevel': 'SLC',
        'start': config['start_date'],
        'end': config['end_date'],
        'flightDirection': config['orbit_direction'].upper(),
        'intersectsWith': config['region_wkt']
    }
    
    if config['polarization']:
        params['polarization'] = config['polarization']
    
    if config['selected_path']:
        params['relativeOrbit'] = int(config['selected_path'])
    if config['selected_frame']:
        params['frame'] = int(config['selected_frame'])
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            logger.info(f"Attempt {attempt + 1}/{max_retries} to search SLC images")
            results = asf.search(**params)
            logger.info(f"Found {len(results)} SLC images before filtering")
            
            # Skip coverage filter if min_coverage is 0
            if config['min_coverage'] == 0:
                logger.info("Coverage filter disabled (min_coverage=0)")
                return results
            
            # Convert region WKT to shapely geometry
            region_geom = loads(config['region_wkt'])
            
            # Filter by coverage
            filtered_results = []
            for prod in results:
                try:
                    footprint_wkt = prod.properties.get('footprint')
                    if not footprint_wkt:
                        logger.debug(f"No footprint for {prod.properties['fileID']}, assuming full coverage")
                        filtered_results.append(prod)
                        continue
                    
                    footprint_geom = loads(footprint_wkt)
                    if not isinstance(footprint_geom, Polygon):
                        logger.warning(f"Invalid footprint geometry for {prod.properties['fileID']}")
                        continue
                    
                    intersection = region_geom.intersection(footprint_geom)
                    coverage = (intersection.area / region_geom.area) * 100
                    if coverage >= config['min_coverage']:
                        filtered_results.append(prod)
                        logger.info(f"Image {prod.properties['fileID']} coverage: {coverage:.2f}%")
                    else:
                        logger.info(f"Image {prod.properties['fileID']} skipped, coverage {coverage:.2f}% < {config['min_coverage']}%")
                except Exception as e:
                    logger.error(f"Error calculating coverage for {prod.properties['fileID']}: {str(e)}")
            
            logger.info(f"Filtered to {len(filtered_results)} SLC images with coverage >= {config['min_coverage']}%")
            
            if len(filtered_results) < config['min_images']:
                logger.warning(f"Only {len(filtered_results)} images found, less than min_images={config['min_images']}. Proceeding anyway.")
            
            return filtered_results
        except Exception as e:
            logger.warning(f"Search attempt {attempt + 1} failed: {str(e)}")
            if attempt < max_retries - 1:
                logger.info("Retrying after 10 seconds...")
                time.sleep(10)
            else:
                logger.error(f"Error searching SLC images after {max_retries} attempts: {str(e)}")
                return []

def download_orbit(sensing_datetime, satellite='S1A', prefer_orbit_type='POEORB'):
    try:
        # Convert sensing_datetime to naive if it is aware
        if sensing_datetime.tzinfo is not None:
            sensing_datetime = sensing_datetime.replace(tzinfo=None)
        
        year = sensing_datetime.strftime('%Y')
        month = sensing_datetime.strftime('%m')
        
        orbit_types = [prefer_orbit_type, 'RESORB'] if prefer_orbit_type == 'POEORB' else ['RESORB', 'POEORB']
        
        # Fix satellite name to S1A or S1B
        satellite_code = 'S1' + satellite[-1]  # 'A' or 'B'
        
        for orbit_type in orbit_types:
            base_url = f"https://step.esa.int/auxdata/orbits/Sentinel-1/{orbit_type}/{satellite_code}/{year}/{month}/"
            
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    logger.info(f"Fetching {orbit_type} files from {base_url} (Attempt {attempt + 1}/{max_retries})")
                    response = requests.get(base_url, timeout=30)
                    response.raise_for_status()
                    soup = BeautifulSoup(response.text, 'html.parser')
                    
                    links = [a['href'] for a in soup.find_all('a', href=True) if a['href'].endswith('.EOF.zip')]
                    logger.info(f"Found {len(links)} orbit files: {links}")
                    
                    for link in links:
                        if f"S1{satellite_code[-1]}_OPER_AUX_{orbit_type}" in link:
                            parts = link.split('_')
                            if len(parts) >= 8:
                                validity_start_str = parts[6][1:]
                                validity_end_str = parts[7].split('.')[0]
                                try:
                                    validity_start = datetime.strptime(validity_start_str, '%Y%m%dT%H%M%S')
                                    validity_end = datetime.strptime(validity_end_str, '%Y%m%dT%H%M%S')
                                    logger.info(f"Checking orbit file: {link}")
                                    logger.info(f"sensing_datetime: {sensing_datetime}, tz: {sensing_datetime.tzinfo}")
                                    logger.info(f"validity_start: {validity_start}, tz: {validity_start.tzinfo}")
                                    logger.info(f"validity_end: {validity_end}, tz: {validity_end.tzinfo}")
                                    if validity_start <= sensing_datetime < validity_end:
                                        file_url = base_url + link
                                        zip_path = os.path.join(ORBIT_DIR, link)
                                        if not os.path.exists(zip_path):
                                            logger.info(f"Downloading {orbit_type} ZIP: {link}")
                                            resp = requests.get(file_url, timeout=30)
                                            resp.raise_for_status()
                                            with open(zip_path, 'wb') as f:
                                                f.write(resp.content)
                                            logger.info(f"Downloaded {orbit_type} ZIP: {link}")
                                        else:
                                            logger.info(f"{orbit_type} ZIP already exists: {link}")
                                        
                                        eof_path = os.path.join(ORBIT_DIR, link.replace('.zip', ''))
                                        if not os.path.exists(eof_path):
                                            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                                                zip_ref.extractall(ORBIT_DIR)
                                                for extracted_file in zip_ref.namelist():
                                                    if extracted_file.endswith('.EOF'):
                                                        extracted_eof = os.path.join(ORBIT_DIR, extracted_file)
                                                        os.rename(extracted_eof, eof_path)
                                                        logger.info(f"Extracted {orbit_type} EOF to: {eof_path}")
                                                        break
                                            os.remove(zip_path)
                                            logger.info(f"Removed ZIP: {zip_path}")
                                        return eof_path
                                except ValueError as ve:
                                    logger.warning(f"Invalid date in {link}: {ve}")
                                    continue
                    break
                except Exception as e:
                    logger.warning(f"{orbit_type} fetch attempt {attempt + 1} failed: {str(e)}")
                    if attempt < max_retries - 1:
                        time.sleep(5)
        
        logger.error("No orbit file found")
        return None
    except Exception as e:
        logger.error(f"Error downloading orbit: {str(e)}")
        return None

def download_single_slc(product):
    try:
        session = asf.ASFSession().auth_with_creds(USERNAME, PASSWORD)
        session.timeout = 600
        
        download_url = product.properties['url']
        file_name = product.properties['fileID'] + '.zip'
        local_path = os.path.join(OUTPUT_DIR, file_name)
        
        if os.path.exists(local_path):
            logger.info(f"SLC already exists: {file_name}")
            return local_path
        
        max_retries = 5
        for attempt in range(max_retries):
            try:
                logger.info(f"Downloading SLC {file_name} (attempt {attempt + 1})")
                with session.get(download_url, stream=True, timeout=600) as response:
                    response.raise_for_status()
                    total_size = int(response.headers.get('content-length', 0))
                    downloaded_size = 0
                    chunk_size = 8192
                    with open(local_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=chunk_size):
                            if chunk:
                                f.write(chunk)
                                downloaded_size = downloaded_size + len(chunk)
                                if total_size > 0:
                                    progress = (downloaded_size / total_size) * 100
                                    if int(progress) % 5 == 0:
                                        logger.info(f"{file_name} progress: {progress:.1f}%")
                logger.info(f"SLC downloaded: {local_path}")
                return local_path
            except Exception as e:
                logger.warning(f"Download attempt {attempt + 1} failed for {file_name}: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(15)
        return None
    except Exception as e:
        logger.error(f"Error downloading SLC {product.properties['fileID']}: {str(e)}")
        return None

def download_slc_batch(products, batch_size, num_threads):
    logger.info(f"Downloading SLC images in batches of {batch_size} with {num_threads} threads")
    all_paths = []
    for i in range(0, len(products), batch_size):
        batch = products[i:i + batch_size]
        with ThreadPoolExecutor(max_workers=num_threads) as executor:
            future_to_product = {executor.submit(download_single_slc, prod): prod for prod in batch}
            for future in as_completed(future_to_product):
                prod = future_to_product[future]
                try:
                    path = future.result()
                    if path:
                        all_paths.append(path)
                except Exception as exc:
                    logger.error(f"Batch download for {prod.properties['fileID']} generated exception: {exc}")
        time.sleep(5)
    return all_paths

def unzip_files(zip_paths):
    logger.info("Unzipping downloaded files...")
    extracted_paths = []
    for zip_path in zip_paths:
        if not os.path.exists(zip_path):
            continue
        extract_dir = os.path.dirname(zip_path)
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(extract_dir)
            logger.info(f"Unzipped: {zip_path}")
            extracted_paths.append(extract_dir)
            os.remove(zip_path)
        except Exception as e:
            logger.error(f"Error unzipping {zip_path}: {str(e)}")
    return extracted_paths

def download_dem(config):
    if not config['download_dem'] or os.path.exists(DEM_FILE):
        logger.info("DEM already exists or download disabled.")
        return True
    
    logger.info(f"Downloading USGS SRTM DEM at {config['dem_resolution']} resolution")
    
    lon_min, lat_min, lon_max, lat_max = map(float, config['bbox_coordinates'].split(','))
    
    # Calculate tiles
    lat_tiles = range(int(np.floor(lat_min)), int(np.ceil(lat_max)))
    lon_tiles = range(int(np.floor(lon_min)), int(np.ceil(lon_max)))
    
    dem_tiles = []
    for lat in lat_tiles:
        for lon in lon_tiles:
            lat_str = f"N{abs(lat):02d}" if lat >= 0 else f"S{abs(lat):02d}"
            lon_str = f"E{abs(lon):03d}" if lon >= 0 else f"W{abs(lon):03d}"
            if config['dem_resolution'] == '30m':
                tile_name = f"{lat_str}{lon_str}.SRTMGL1.hgt.zip"
                url = f"https://e4ftl01.cr.usgs.gov/MEASURES/SRTMGL1.003/2000.02.11/{tile_name}"
            else:  # 90m
                tile_name = f"{lat_str}{lon_str}.SRTMGL3.hgt.zip"
                url = f"https://e4ftl01.cr.usgs.gov/MEASURES/SRTMGL3.003/2000.02.11/{tile_name}"
            
            local_zip = os.path.join(DEM_DIR, tile_name)
            hgt_path = os.path.join(DEM_DIR, f"{lat_str}{lon_str}.hgt")
            
            if os.path.exists(hgt_path):
                logger.info(f"Tile already exists: {hgt_path}")
                dem_tiles.append(hgt_path)
                continue
            
            try:
                logger.info(f"Downloading DEM tile: {tile_name}")
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                with open(local_zip, 'wb') as f:
                    f.write(resp.content)
                with zipfile.ZipFile(local_zip, 'r') as zip_ref:
                    zip_ref.extractall(DEM_DIR)
                os.remove(local_zip)
                if os.path.exists(hgt_path):
                    logger.info(f"Downloaded and extracted tile: {hgt_path}")
                    dem_tiles.append(hgt_path)
                else:
                    logger.error(f"Tile {hgt_path} not found after extraction")
                    continue
            except Exception as e:
                logger.warning(f"Failed to download or extract tile {tile_name}: {str(e)}")
                continue
    
    if not dem_tiles:
        logger.error("No DEM tiles downloaded.")
        return False
    
    try:
        if len(dem_tiles) == 1:
            logger.info("Only one DEM tile found, copying to output without merging.")
            with rasterio.open(dem_tiles[0]) as src:
                out_meta = src.meta.copy()
                out_meta.update({
                    "driver": "GTiff",
                    "crs": CRS.from_epsg(4326)
                })
                with rasterio.open(DEM_FILE, "w", **out_meta) as dest:
                    dest.write(src.read())
            logger.info(f"DEM saved to: {DEM_FILE}")
            return True
        else:
            for tile in dem_tiles:
                if not os.path.exists(tile):
                    logger.error(f"Tile {tile} does not exist for merging")
                    return False
            src_files = [rasterio.open(tile) for tile in dem_tiles]
            mosaic, out_trans = merge(src_files)
            
            out_meta = src_files[0].meta.copy()
            out_meta.update({
                "driver": "GTiff",
                "height": mosaic.shape[1],
                "width": mosaic.shape[2],
                "transform": out_trans,
                "crs": CRS.from_epsg(4326)
            })
            
            with rasterio.open(DEM_FILE, "w", **out_meta) as dest:
                dest.write(mosaic)
            
            for src in src_files:
                src.close()
            
            logger.info(f"DEM merged and saved to: {DEM_FILE}")
            return True
    except Exception as e:
        logger.error(f"Error processing DEM tiles: {str(e)}")
        return False

def main(config):
    logger.info("Authenticated with ASF successfully")
    
    # Step 1: Download DEM
    dem_success = download_dem(config)
    if not dem_success and not config['continue_without_dem']:
        logger.error("DEM download failed and continue_without_dem is false. Exiting.")
        exit(1)
    
    # Step 2: List images and sort by sensing time
    products = search_slc_images(config)
    if not products:
        logger.error("No SLC images found. Exiting.")
        exit(1)
    
    # Sort products by sensing time
    products = sorted(products, key=lambda x: datetime.fromisoformat(x.properties['startTime'].replace(' ', 'T').split('.')[0]))
    
    # Write search results to search_results.txt
    search_results_path = os.path.join(OUTPUT_DIR, 'search_results.txt')
    with open(search_results_path, 'w') as f:
        f.write("# Format: Each line contains \"filename - date (YYYY-MM-DD)\". Example:\n")
        f.write("# S1A_IW_SLC__1SDV_20230101T033123_20230101T033150_046789_059A3F_1234.SAFE - 2023-01-01\n")
        for prod in products:
            file_id = prod.properties['fileID']
            sensing_time = datetime.fromisoformat(prod.properties['startTime'].replace(' ', 'T').split('.')[0])
            date_str = sensing_time.strftime('%Y-%m-%d')
            f.write(f"{file_id}.SAFE - {date_str}\n")
    logger.info(f"Search results written to: {search_results_path}")
    
    logger.info("List of selected SLC images:")
    for prod in products:
        sensing_time = prod.properties.get('startTime', 'Unknown')
        file_id = prod.properties['fileID']
        logger.info(f"- {file_id} (Sensing: {sensing_time})")
    
    # Step 3: Download and unzip orbits
    logger.info("Downloading and unzipping orbits...")
    orbit_paths = {}
    orbit_zip_paths = []
    for prod in products:
        sensing_str = prod.properties.get('startTime', '').split('.')[0]
        try:
            sensing_dt = datetime.fromisoformat(sensing_str.replace(' ', 'T'))
            # Ensure sensing_dt is naive
            if sensing_dt.tzinfo is not None:
                sensing_dt = sensing_dt.replace(tzinfo=None)
            satellite = 'S1' + prod.properties['platform'][-1]
            orbit_path = download_orbit(sensing_dt, satellite, config['prefer_orbit_type'])
            orbit_paths[prod.properties['fileID']] = orbit_path
            if orbit_path and orbit_path.endswith('.zip'):
                orbit_zip_paths.append(orbit_path)
            if not orbit_path:
                logger.warning(f"Orbit not found for {prod.properties['fileID']}")
        except Exception as e:
            logger.warning(f"Failed to parse datetime for {prod.properties['fileID']}: {str(e)}")
    
    unzip_files(orbit_zip_paths)
    
    # Step 4: Download and unzip SLCs
    slc_zip_paths = download_slc_batch(products, config['batch_size'], config['num_threads'])
    unzip_files(slc_zip_paths)
    
    logger.info("All downloads completed successfully!")
    print("Download Summary:")
    print(f"- SLC Images: {len(slc_zip_paths)} downloaded to {OUTPUT_DIR}")
    print(f"- Orbits: {sum(1 for p in orbit_paths.values() if p)} downloaded to {ORBIT_DIR}")
    print(f"- DEM: {DEM_FILE if dem_success else 'Failed'}")
    
    exit(0)

if __name__ == "__main__":
    try:
        config = parse_config('config_sentinel_download_asf.txt')
        main(config)
    except Exception as e:
        logger.error(f"Error in main process: {str(e)}")
        exit(1)