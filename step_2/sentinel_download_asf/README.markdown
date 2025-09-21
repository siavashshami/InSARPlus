# Sentinel-1 SLC Image Download Script using ASF

## Overview
This script downloads Sentinel-1 Single Look Complex (SLC) images, precise orbit files (POEORB or RESORB), and Digital Elevation Model (DEM) data from the Alaska Satellite Facility (ASF) based on user-defined criteria such as date range, region, polarization, orbit direction, path, frame, and minimum coverage percentage. It supports parallel downloads with threading, batch processing, and automatic unzipping of files. The script ensures that only images meeting a minimum coverage threshold are downloaded and handles orbit files specific to each image's sensing time.

The script uses the `asf_search` library for querying and downloading from the ASF API, `rasterio` for DEM merging, and geometric libraries like `shapely` and `geopandas` for coverage calculations. It includes retry mechanisms for network errors, progress logging, and graceful handling of failures (e.g., continuing without DEM if specified).

This tool is particularly useful for preparing data for radar interferometry (InSAR) time-series analysis, where consistent geometry (same path and frame) and appropriate polarization are critical.

## Prerequisites
- **Python Version**: Python 3.8 or higher.
- **Required Libraries**: The script depends on the following Python libraries. Install them using pip:
  ```bash
  pip install asf_search requests beautifulsoup4 rasterio geopandas shapely fiona numpy
  ```
  Note: `rasterio` and `geopandas` may require additional system dependencies like GDAL and Fiona. On Ubuntu, install with:
  ```bash
  sudo apt install libgdal-dev libproj-dev
  ```
  On Windows/macOS, refer to the [rasterio](https://rasterio.readthedocs.io/en/stable/installation.html) and [geopandas](https://geopandas.org/en/stable/getting_started/install.html) documentation for conda or wheel installations.

- **ASF Account**: You need a free account from [Earthdata Login](https://urs.earthdata.nasa.gov) to access ASF data. Provide your username and password in the config file.

- **No Internet Restrictions**: The script queries the ASF API and ESA orbit servers, so ensure your network allows access to:
  - https://api.daac.asf.alaska.edu
  - https://step.esa.int

## Installation
1. Clone or download the script files: `sentinel_download_asf.py` and `config_sentinel_download_asf.txt`.
2. Install the required libraries as mentioned above.
3. Place the config file in the same directory as the script.

## Configuration
Edit the `config_sentinel_download_asf.txt` file to set your parameters. The file uses INI-style sections for clarity:

- **[Credentials]**:
  ```ini
  username: your_username
  password: your_password
  ```
  Enter your ASF username and password. These are required and must be provided directly in the file (no environment variables).

- **[General]**:
  - `data_source`: Fixed to 'asf' for Alaska Satellite Facility.
  - `start_date` and `end_date`: Date range in YYYY-MM-DD format (e.g., 2019-01-01 to 2019-12-31).
  - `platform`: 'S1A' for Sentinel-1A, 'S1B' for Sentinel-1B, or 'both'.
  - `orbit_direction`: 'ascending' or 'descending'.
  - `polarization`: e.g., 'VV' for single-pol, 'VV+VH' for dual-pol (valid: VV, VH, HH, HV or combinations).

- **[Region]**:
  Define the search region. Set `region_type` to one of: `bounding_box`, `point_buffer`, `shapefile`, `geojson`, `kml`, `kmz`. Only fill the relevant field; others are ignored.
  - For `bounding_box`: Provide `bbox_coordinates` as lon_min, lat_min, lon_max, lat_max (e.g., 51.0438, 35.5146, 51.6138, 35.8958).
  - For `point_buffer`: Provide `point_buffer` as center_lon, center_lat, radius_km (e.g., 51.3515, 35.7053, 15).
  - For `shapefile`/`geojson`/`kml`/`kmz`: Set `region_folder` (default: study_area) and specify the filename (e.g., `shapefile: study_area.shp`). Ensure supporting files (.shx, .dbf for shapefile) are present.

- **[Processing]**:
  - `min_coverage`: Minimum region coverage percentage for images (0-100, default 100).
  - `min_images`: Minimum number of images required (e.g., 10; warning if fewer).
  - `batch_size`: Images per download batch (e.g., 10).
  - `num_threads`: CPU threads for parallel downloads (default: 4).

- **[Output]**:
  - `log_file`: Path for logs (e.g., sentinel/download_asf.log).
  - `output_dir`: Folder for SLC images (e.g., sentinel/images).
  - `orbit_dir`: Folder for orbit files (e.g., sentinel/orbits).
  - `prefer_orbit_type`: 'POEORB' (precise, preferred) or 'RESORB' (fallback).
  - `dem_file`: Output DEM path (e.g., sentinel/dem/dem.tif).
  - `download_dem`: `true`/`false` to download DEM.
  - `continue_without_dem`: `true`/`false` to proceed if DEM fails.
  - `dem_source`: Fixed to 'usgs' for SRTM.
  - `dem_resolution`: '30m' or '90m'.

- **[Selection]**:
  - `selected_path`: Relative orbit path number (e.g., 28; leave empty for all).
  - `selected_frame`: Frame number (e.g., 112; leave empty for all in path).

If the config file is missing or invalid, the script raises clear errors with instructions.

## How to Run
1. Ensure the config file is set up correctly (e.g., valid credentials and region).
2. Run the script from the command line:
   ```bash
   python sentinel_download_asf.py
   ```
3. The script will:
   - Parse the config and set up directories/logs.
   - Download and merge DEM (if enabled).
   - Search for matching SLC images (with coverage filtering).
   - Download precise orbits for each image.
   - Download SLC images in batches with progress logging.
   - Unzip all files automatically.
   - Output a summary (e.g., number of SLCs, orbits, DEM status).

Downloads are resumable (skips existing files). Check `sentinel/download_asf.log` for details. If fewer than `min_images` are found, it proceeds with a warning.

## Code Explanation
The script is structured modularly for maintainability:

- **setup_logging()**: Configures logging to file and console with timestamps and line numbers.
- **parse_config()**: Reads and validates the INI config, computes region WKT geometry (using shapely/geopandas for buffers/shapefiles), sets global paths, and creates output directories.
- **search_slc_images()**: Queries ASF API with parameters (platform, dates, orbit, polarization, region intersects). Filters by coverage using shapely intersection/area calculations. Includes retries (up to 3) for API errors.
- **download_orbit()**: Fetches and extracts precise orbit ZIPs from ESA servers by sensing time, preferring POEORB. Parses file links with BeautifulSoup and matches validity periods.
- **download_single_slc()**: Downloads a single SLC ZIP via ASF session with streaming and progress (5% increments). Retries up to 5 times.
- **download_slc_batch()**: Parallelizes downloads using ThreadPoolExecutor (batches + threads) with 5-second delays between batches.
- **unzip_files()**: Extracts ZIPs and removes originals.
- **download_dem()**: Downloads USGS SRTM tiles (30m/90m) for the region bounding box, extracts HGT files, and merges them into a GeoTIFF using rasterio.
- **main()**: Orchestrates the workflow: DEM → search → orbits → SLCs. Handles exceptions and prints a final summary.

Global variables (e.g., USERNAME, OUTPUT_DIR) are set during parsing for efficiency. All functions log actions and errors verbosely.

## References and Official Resources
For more on ASF Sentinel-1 downloads:
- ASF Search API Keywords & Endpoints: [https://docs.asf.alaska.edu/api/keywords/](https://docs.asf.alaska.edu/api/keywords/)
- asf_search Python Package Basics: [https://docs.asf.alaska.edu/asf_search/basics/](https://docs.asf.alaska.edu/asf_search/basics/)
- Download API Basics: [https://docs.asf.alaska.edu/api/basics/](https://docs.asf.alaska.edu/api/basics/)
- ASF SAR Data Download Manual: [https://docs.asf.alaska.edu/asf_search/downloading/](https://docs.asf.alaska.edu/asf_search/downloading/)
- asf_search Best Practices: [https://docs.asf.alaska.edu/asf_search/BestPractices/](https://docs.asf.alaska.edu/asf_search/BestPractices/)
- NASA Earthdata Sentinel-1 Page: [https://www.earthdata.nasa.gov/data/platforms/space-based-platforms/sentinel-1](https://www.earthdata.nasa.gov/data/platforms/space-based-platforms/sentinel-1)
- ESA Precise Orbit Files: [https://sarstep-terrasar.com/auxiliary-data/](https://sarstep-terrasar.com/auxiliary-data/)
- USGS SRTM Documentation: [https://www.usgs.gov/centers/eros/science/usgs-eros-archive-digital-elevation-global-30-arc-second-elevation](https://www.usgs.gov/centers/eros/science/usgs-eros-archive-digital-elevation-global-30-arc-second-elevation)

### Why Images Should Be in the Same Path and Frame
For reliable InSAR processing, all images must share the same relative orbit path and frame to ensure consistent incidence angles, look direction, and minimal geometric baseline variations, enabling accurate coregistration and phase coherence. This reduces decorrelation from orbital differences.

- De Zan, M., et al. (2021). "Relative / Absolute Orbit number interpretation." ESA SNAP/STEP Forum. Available at: [https://forum.step.esa.int/t/relative-absolute-orbit-number-interpretation/34049](https://forum.step.esa.int/t/relative-absolute-orbit-number-interpretation/34049) (Explains that images from the same relative orbit have identical incidence angles and look direction for multi-temporal coregistration.)
- Yagüe-Martínez, N., et al. (2023). "Utilising Sentinel-1's orbital stability for efficient pre-processing of repeat-pass RTC products." *ISPRS Journal of Photogrammetry and Remote Sensing*, 201, 1-15. [https://doi.org/10.1016/j.isprsjprs.2023.05.025](https://doi.org/10.1016/j.isprsjprs.2023.05.025) (Discusses how Sentinel-1's 175 relative orbits ensure stable geometry for InSAR, minimizing baseline dispersion.)
- Ali, I., et al. (2023). "Sentinel-1 InSAR-derived land subsidence assessment along the Himalayan Front." *International Journal of Applied Earth Observation and Geoinformation*, 125, 103568. [https://doi.org/10.1016/j.jag.2023.103568](https://doi.org/10.1016/j.jag.2023.103568) (Highlights orbital control's role in reducing geometrical baselines for coherence in subsidence monitoring.)
- Sadeghi, Zahra, et al. "Benchmarking and inter-comparison of Sentinel-1 InSAR velocities and time series." Remote Sensing of Environment 256 (2021): 112306. [https://eprints.whiterose.ac.uk/id/eprint/162927/1/Sadeghietal_final.pdf](https://doi.org/10.1016/j.rse.2021.112306)

### Polarization Selection in Radar Interferometry
In Sentinel-1 InSAR, co-polarizations like VV are preferred over cross-polarizations (e.g., VH) because they provide higher coherence for phase-based interferometry, as cross-pol channels exhibit more volume scattering and decorrelation in vegetated or rough terrains. VV is standard for most deformation applications.

- Alaska Satellite Facility (ASF). (2023). "Sentinel-1 InSAR Product Guide." *HyP3 Documentation*. Available at: [https://hyp3-docs.asf.alaska.edu/guides/insar_product_guide/](https://hyp3-docs.asf.alaska.edu/guides/insar_product_guide/) (States that InSAR processing uses co-pol (VV) data, not cross-pol (VH), for optimal phase preservation.)
- Pipia, L., et al. (2023). "Sentinel-1 Polarization Comparison for Flood Segmentation Using Deep Learning." *Proceedings*, 87(1), 14. [https://doi.org/10.3390/proceedings2023087014](https://doi.org/10.3390/proceedings2023087014) (Compares VV and VH; VV yields higher accuracy (IOU 67.35%) due to better signal-to-noise in water/land interfaces.)
- Nagler, T., et al. (2015). "The Sentinel-1 Mission: New Opportunities for Ice Sheet and Glacier Monitoring." *AGU Fall Meeting Abstracts*. American Geophysical Union. (Recommends VV for InSAR coherence in cryospheric applications, as VH is more suited for scattering analysis than phase interferometry.)

## Troubleshooting
- Check `sentinel/download_asf.log` for detailed errors (e.g., API timeouts, invalid geometries).
- Common issues:
  - **Invalid credentials**: Verify Earthdata login at [https://urs.earthdata.nasa.gov](https://urs.earthdata.nasa.gov).
  - **Network errors**: Increase retries or check firewall (script retries automatically).
  - **No images found**: Widen date range, lower `min_coverage`, or verify region/path/frame.
  - **DEM failures**: Set `continue_without_dem: true` or check USGS tile availability.
  - **Library issues**: Ensure GDAL is installed; test with:
    ```bash
    python -c "import rasterio; print(rasterio.__version__)"
    ```
- For large downloads, monitor disk space; SLC files are ~5-10 GB each.