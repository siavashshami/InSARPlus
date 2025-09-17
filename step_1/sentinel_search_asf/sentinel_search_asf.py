import os
import asf_search as asf
import geopandas as gpd
import configparser
import logging
from datetime import datetime, timedelta
from shapely.geometry import Point, box, shape
import matplotlib.pyplot as plt
import numpy as np
from shapely import wkt
import time

logger = None

def setup_logging(log_file):
    global logger
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG)
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(levelname)s - Line %(lineno)d - %(message)s')
    )
    logger.addHandler(console_handler)
    os.makedirs(os.path.dirname(log_file) if os.path.dirname(log_file) else '.', exist_ok=True)
    file_handler = logging.FileHandler(log_file, mode='w')
    file_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(levelname)s - Line %(lineno)d - %(message)s')
    )
    logger.addHandler(file_handler)
    return logger

def create_default_config(config_file):
    config_content = """[Credentials]
username: 
password: 
[General]
data_source: asf
start_date: 2016-01-01
end_date: 2024-12-31
min_images: 10
coverage_percent: 100
[Region]
region_type: bounding_box
region_folder: study_area
bounding_box: 51.1453, 35.5941, 51.5932, 35.8191
point_buffer: 
shapefile: 
geojson: 
kml: 
kmz: 
"""
    with open(config_file, 'w') as f:
        f.write(config_content)
    logger.info(f"Default config file created: {config_file}")

def read_config(config_file):
    global logger
    if logger is None:
        default_log_file = os.path.join('sentinel', 'search.log')
        os.makedirs(os.path.dirname(default_log_file), exist_ok=True)
        logger = setup_logging(default_log_file)
    config = configparser.ConfigParser()
    if not os.path.exists(config_file):
        logger.info(f"Config file {config_file} not found, creating default")
        create_default_config(config_file)
    config.read(config_file)
    config_dict = {}
    for section in config.sections():
        for key, value in config.items(section):
            config_dict[key] = value
    required_keys = ['data_source', 'username', 'password', 'start_date', 'end_date', 'region_type', 'region_folder']
    for key in required_keys:
        if key not in config_dict:
            error_msg = f"Missing required config key: {key}. Please add '{key}' to the appropriate section in the config file and try again."
            logger.error(error_msg)
            raise KeyError(error_msg)
    config_dict['min_images'] = config_dict.get('min_images', '10')
    try:
        config_dict['min_images'] = int(config_dict['min_images'])
        if config_dict['min_images'] <= 0:
            error_msg = "min_images must be a positive integer. Please update the 'min_images' value in the [General] section of the config file to a positive integer and try again."
            logger.error(error_msg)
            raise ValueError(error_msg)
    except ValueError:
        error_msg = f"Invalid min_images: {config_dict['min_images']}. Must be a positive integer. Please correct the 'min_images' value in the [General] section of the config file and try again."
        logger.error(error_msg)
        raise ValueError(error_msg)
    config_dict['coverage_percent'] = config_dict.get('coverage_percent', '100')
    try:
        config_dict['coverage_percent'] = float(config_dict['coverage_percent'])
        if not (0 < config_dict['coverage_percent'] <= 100):
            error_msg = "coverage_percent must be greater than 0 and less than or equal to 100. Please update the 'coverage_percent' value in the [General] section of the config file and try again."
            logger.error(error_msg)
            raise ValueError(error_msg)
    except ValueError:
        error_msg = f"Invalid coverage_percent: {config_dict['coverage_percent']}. Must be greater than 0 and less than or equal to 100. Please correct the 'coverage_percent' value in the [General] section of the config file and try again."
        logger.error(error_msg)
        raise ValueError(error_msg)
    if not config_dict['username'] or not config_dict['password']:
        error_msg = "Username and password must be provided in the [Credentials] section of the config file. Please add your 'username' and 'password' there and try again."
        logger.error(error_msg)
        raise ValueError(error_msg)
    if config_dict['data_source'].lower() != 'asf':
        error_msg = f"Invalid data_source: {config_dict['data_source']}. Only 'asf' is supported. Please set 'data_source' to 'asf' in the [General] section of the config file and try again."
        logger.error(error_msg)
        raise ValueError(error_msg)
    for date_key in ['start_date', 'end_date']:
        try:
            datetime.strptime(config_dict[date_key], '%Y-%m-%d')
        except ValueError:
            error_msg = f"Invalid date format for {date_key}: {config_dict[date_key]}. Use YYYY-MM-DD format. Please correct the '{date_key}' value in the [General] section of the config file and try again."
            logger.error(error_msg)
            raise ValueError(error_msg)
    region_type = config_dict['region_type'].lower()
    region_fields = {
        'bounding_box': 'bounding_box',
        'point_buffer': 'point_buffer',
        'shapefile': 'shapefile',
        'geojson': 'geojson',
        'kml': 'kml',
        'kmz': 'kmz'
    }
    used_field = region_fields.get(region_type)
    if used_field and used_field not in config_dict:
        error_msg = f"Missing required field '{used_field}' for region_type={region_type}. Please add '{used_field}' to the [Region] section of the config file with the appropriate value and try again."
        logger.error(error_msg)
        raise ValueError(error_msg)
    for field in region_fields.values():
        if field != used_field and field in config_dict and config_dict[field]:
            logger.warning(f"Ignoring unused field '{field}' for region_type={region_type}")
    return config_dict

def point_buffer_to_polygon(lat, lon, radius_km):
    try:
        point = Point(lon, lat)
        buffer_deg = radius_km / 111.0  # Approximate conversion from km to degrees
        return point.buffer(buffer_deg)
    except Exception as e:
        error_msg = f"Error creating point buffer: {str(e)}. Please check the 'point_buffer' values in the [Region] section of the config file (format: center_lon, center_lat, radius_km) and try again."
        logger.error(error_msg)
        raise ValueError(error_msg)

def plot_temporal(group_key, image_info, output_dir):
    try:
        os.makedirs(output_dir, exist_ok=True)
        if not image_info:
            logger.warning(f"No images to plot for {group_key}")
            return
        sorted_images = sorted(image_info, key=lambda x: datetime.strptime(x['date'], '%Y-%m-%d'))
        dates = [datetime.strptime(img['date'], '%Y-%m-%d') for img in sorted_images]
        y_vals = np.zeros(len(dates))
        plt.figure(figsize=(10, 3))
        plt.scatter(dates, y_vals, c='green', marker='o', s=50, label='Image Dates')
        if len(dates) > 1:
            plt.plot(dates, y_vals, color='black', linestyle='-', label='Timeline')
        gap_dates = []
        gap_points = []
        for i in range(len(dates) - 1):
            delta_days = (dates[i+1] - dates[i]).days
            if delta_days > 12:
                mid_date = dates[i] + timedelta(days=delta_days / 2)
                gap_dates.append(mid_date)
                gap_points.append(0)
        if gap_dates:
            plt.scatter(gap_dates, gap_points, c='red', marker='o', s=50, label='Temporal Gaps (>12 days)')
        plt.xlabel('Date')
        plt.yticks([])
        plt.title(f'Temporal Distribution of Images for {group_key}')
        plt.legend(loc='upper right')
        plt.grid(True, axis='x')
        safe_group_key = group_key.replace(':', '_').replace(' ', '_')
        plot_file = os.path.join(output_dir, f'temporal_plot_{safe_group_key}.png')
        plt.savefig(plot_file, dpi=300, bbox_inches='tight')
        plt.close()
        logger.info(f"Temporal plot saved: {plot_file}")
    except Exception as e:
        error_msg = f"Error plotting temporal data for {group_key}: {str(e)}. Please ensure matplotlib and numpy are installed and check the image data."
        logger.error(error_msg)

def calculate_coverage_percent(region_geom, product_geom):
    try:
        intersection = region_geom.intersection(product_geom)
        if intersection.is_empty:
            return 0.0
        region_area = region_geom.area
        if region_area == 0:
            return 0.0
        coverage = (intersection.area / region_area) * 100.0
        return coverage
    except Exception as e:
        error_msg = f"Error calculating coverage percent: {str(e)}. Please verify the region geometry in the config file and ensure shapely is installed correctly."
        logger.error(error_msg)
        return 0.0

def search_images_asf(config, region_geom, wkt_footprint, username, password):
    try:
        search_results_file = os.path.join('sentinel', 'search_results_asf.txt')
        raw_api_log = os.path.join('sentinel', 'raw_api_responses_asf.log')
        os.makedirs(os.path.dirname(search_results_file), exist_ok=True)
        os.makedirs(os.path.dirname(raw_api_log), exist_ok=True)
        with open(search_results_file, 'w') as f:
            f.write(f"Sentinel-1 SLC Search Results ASF (Groups >{config['min_images']} images only, Coverage >= {config['coverage_percent']}%)\n")
            f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Region: {wkt_footprint}\n")
            f.write(f"Data Source: {config['data_source']}\n")
            f.write(f"Date Range: {config['start_date']} to {config['end_date']}\n\n")
        all_products = []
        start_date = datetime.strptime(config['start_date'], '%Y-%m-%d')
        end_date = datetime.strptime(config['end_date'], '%Y-%m-%d')
        date_step = timedelta(days=180)
        platforms = ['Sentinel-1A', 'Sentinel-1B']
        orbit_directions = ['ASCENDING', 'DESCENDING']
        polarizations = ['VV', 'VH', 'HH', 'HV', 'VV+VH', 'HH+HV']
        current_start = start_date
        min_coverage = config['coverage_percent']
        logger.info("Starting ASF comprehensive search over date ranges and parameters with coverage filter.")
        while current_start <= end_date:
            current_end = min(current_start + date_step - timedelta(days=1), end_date)
            logger.info(f"Searching date range: {current_start.strftime('%Y-%m-%d')} to {current_end.strftime('%Y-%m-%d')}")
            for pol in polarizations:
                for orbit_direction in orbit_directions:
                    for platform in platforms:
                        logger.info(f"ASF Search: Polarization={pol}, Orbit={orbit_direction}, Platform={platform}")
                        max_retries = 3
                        retries = 0
                        while retries < max_retries:
                            try:
                                results = asf.geo_search(
                                    platform=platform,
                                    processingLevel='SLC',
                                    start=current_start,
                                    end=current_end,
                                    intersectsWith=wkt_footprint,
                                    flightDirection=orbit_direction,
                                    polarization=pol
                                )
                                with open(raw_api_log, 'a') as f:
                                    f.write(f"Polarization: {pol}, Orbit: {orbit_direction}, Platform: {platform}, Date Range: {current_start.strftime('%Y-%m-%d')} to {current_end.strftime('%Y-%m-%d')}\n")
                                    f.write(f"Response: {results.geojson()}\n\n")
                                logger.info(f"Found {len(results)} products.")
                                for product in results.geojson()['features']:
                                    if 'METADATA_SLC' in product['properties']['fileID']:
                                        continue
                                    properties = product['properties']
                                    filename = properties['fileID']
                                    platform_name = properties['platform']
                                    date = datetime.strptime(properties['startTime'], '%Y-%m-%dT%H:%M:%SZ').strftime('%Y-%m-%d')
                                    frame = properties.get('frameNumber', 0)
                                    path = properties.get('pathNumber', 0)
                                    # Calculate coverage
                                    product_geom = shape(product['geometry'])
                                    coverage = calculate_coverage_percent(region_geom, product_geom)
                                    if coverage < min_coverage:
                                        logger.debug(f"Skipping product {filename} due to coverage {coverage:.2f}% < {min_coverage}%")
                                        continue
                                    all_products.append({
                                        'filename': filename,
                                        'date': date,
                                        'platform': platform_name,
                                        'polarization': pol,
                                        'orbit_direction': orbit_direction,
                                        'path': str(path),
                                        'frame': str(frame),
                                        'coverage_percent': coverage
                                    })
                                break  # Success, exit retry loop
                            except Exception as e:
                                retries += 1
                                error_msg = f"ASF Search error for pol={pol}, orbit={orbit_direction}, platform={platform}: {str(e)}. Retrying ({retries}/{max_retries}) after 5 seconds. If this persists, check your internet connection or ASF API status."
                                logger.error(error_msg)
                                if retries == max_retries:
                                    raise ValueError(error_msg)
                                time.sleep(5)
            current_start = current_end + timedelta(days=1)
        return process_and_plot_groups(all_products, config, search_results_file)
    except Exception as e:
        error_msg = f"Error searching SLC images (ASF): {str(e)}. Please check your config file, internet connection, or contact ASF support if the issue continues."
        logger.error(error_msg)
        raise ValueError(error_msg)

def process_and_plot_groups(all_products, config, search_results_file):
    grouped = {}
    grouped_simple = {}
    min_imgs = config['min_images']
    for p in all_products:
        key_full = (p['polarization'], p['orbit_direction'], p['platform'], p['path'], p['frame'])
        if key_full not in grouped:
            grouped[key_full] = {'count': 0, 'dates': [], 'products': []}
        grouped[key_full]['products'].append(p)
        grouped[key_full]['dates'].append(p['date'])
        grouped[key_full]['count'] += 1
        key_simple = (p['polarization'], p['orbit_direction'], p['path'])
        if key_simple not in grouped_simple:
            grouped_simple[key_simple] = {'count': 0, 'dates': [], 'products': []}
        grouped_simple[key_simple]['products'].append(p)
        grouped_simple[key_simple]['dates'].append(p['date'])
        grouped_simple[key_simple]['count'] += 1
    with open(search_results_file, 'a') as f:
        f.write("Detailed Groups (Polarization, Orbit, Platform, Path, Frame):\n")
        for key, group in grouped.items():
            polar, orbit, platform, path, frame = key
            dates_str = ', '.join(sorted(set(group['dates'])))
            f.write(f"Polarization: {polar}, Orbit: {orbit}, Platform: {platform}, Path: {path}, Frame: {frame}\n")
            f.write(f"Number of Images: {group['count']}\n")
            f.write(f"Dates: {dates_str}\nImages:\n")
            for p in group['products']:
                f.write(f"  - {p['filename']} ({p['date']}) Coverage: {p.get('coverage_percent', 0):.2f}%\n")
            f.write("\n")
        f.write("\nSimple Groups (Polarization, Orbit, Path) - without platform/frame distinction:\n")
        for key, group in grouped_simple.items():
            polar, orbit, path = key
            dates_str = ', '.join(sorted(set(group['dates'])))
            f.write(f"Polarization: {polar}, Orbit: {orbit}, Path: {path}\n")
            f.write(f"Number of Images: {group['count']}\n")
            f.write(f"Dates: {dates_str}\nImages:\n")
            for p in group['products']:
                f.write(f"  - {p['filename']} ({p['date']}) [Platform: {p['platform']}, Frame: {p['frame']}] Coverage: {p.get('coverage_percent', 0):.2f}%\n")
            f.write("\n")
    plot_folder = os.path.join('sentinel', 'plots')
    os.makedirs(plot_folder, exist_ok=True)
    for key, group in grouped.items():
        group_key_str = f"POL_{key[0]}_ORB_{key[1]}_PL_{key[2]}_PATH_{key[3]}_FR_{key[4]}"
        plot_temporal(group_key_str, group['products'], plot_folder)
    for key, group in grouped_simple.items():
        group_key_str = f"POL_{key[0]}_ORB_{key[1]}_PATH_{key[2]}"
        plot_temporal(group_key_str, group['products'], plot_folder)
    logger.info("Grouping and plotting completed.")
    filtered_grouped = {k: v for k,v in grouped.items() if v['count'] > min_imgs}
    filtered_grouped_simple = {k: v for k,v in grouped_simple.items() if v['count'] > min_imgs}
    return filtered_grouped, filtered_grouped_simple

def search_images(config, region_geom, wkt_footprint, username, password):
    return search_images_asf(config, region_geom, wkt_footprint, username, password)

def main():
    global logger
    try:
        config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config_sentinel_search_asf.txt')
        logger = setup_logging('sentinel/search.log')
        logger.info(f"Reading configuration from {config_file}")
        config = read_config(config_file)
        username = config['username']
        password = config['password']
        region_type = config['region_type'].lower()
        if region_type == 'bounding_box':
            if not config.get('bounding_box'):
                error_msg = "bounding_box is required for region_type=bounding_box. Please add 'bounding_box' to the [Region] section of the config file (format: lon_min, lat_min, lon_max, lat_max) and try again."
                logger.error(error_msg)
                raise ValueError(error_msg)
            coords = [float(x) for x in config['bounding_box'].split(',')]
            if len(coords) != 4:
                error_msg = "bounding_box must have exactly 4 values (lon_min, lat_min, lon_max, lat_max). Please correct the 'bounding_box' value in the [Region] section of the config file and try again."
                logger.error(error_msg)
                raise ValueError(error_msg)
            region_geom = box(coords[0], coords[1], coords[2], coords[3])
        elif region_type == 'point_buffer':
            if not config.get('point_buffer'):
                error_msg = "point_buffer is required for region_type=point_buffer. Please add 'point_buffer' to the [Region] section of the config file (format: center_lon, center_lat, radius_km) and try again."
                logger.error(error_msg)
                raise ValueError(error_msg)
            coords = [float(x) for x in config['point_buffer'].split(',')]
            if len(coords) != 3:
                error_msg = "point_buffer must have exactly 3 values (center_lon, center_lat, radius_km). Please correct the 'point_buffer' value in the [Region] section of the config file and try again."
                logger.error(error_msg)
                raise ValueError(error_msg)
            region_geom = point_buffer_to_polygon(coords[1], coords[0], coords[2])
        else:
            file_type = region_type
            file_name = config.get(file_type, f"study_area.{file_type if file_type != 'shapefile' else 'shp'}")
            file_path = os.path.join(config['region_folder'], file_name)
            if not os.path.exists(file_path):
                error_msg = f"Region file {file_path} not found for region_type={region_type}. Please place the file in the '{config['region_folder']}' folder and update the '{file_type}' value in the [Region] section of the config file if needed, then try again."
                logger.error(error_msg)
                raise FileNotFoundError(error_msg)
            gdf = gpd.read_file(file_path)
            region_geom = gdf.geometry.iloc[0]
        wkt_footprint = region_geom.wkt
        logger.info(f"Region geometry loaded for {region_type}")
        logger.info("Starting image search")
        filtered_grouped, filtered_grouped_simple = search_images(config, region_geom, wkt_footprint, username, password)
        if not filtered_grouped:
            warning_msg = f"No images found matching the criteria (groups with more than {config['min_images']} images). Please check your config file settings (e.g., date range, coverage_percent, min_images) or try a larger region/date range."
            logger.warning(warning_msg)
            print(warning_msg)
            return
        print("Search completed. Results saved in sentinel/search_results_asf.txt")
        print("Temporal plots saved in sentinel/plots/")
        print("Update config_sentinel_download.txt with additional parameters and run the download script.")
    except Exception as e:
        error_msg = f"Error in main: {str(e)}. Please review the logs in sentinel/search.log for details and correct the issue (e.g., check config file, dependencies, or network)."
        logger.error(error_msg)
        print(error_msg)
        raise

if __name__ == "__main__":
    main()