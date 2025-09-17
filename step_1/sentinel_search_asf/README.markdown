# Sentinel-1 SLC Image Search Script using ASF

## Overview
This script searches for Sentinel-1 Single Look Complex (SLC) images from the Alaska Satellite Facility (ASF) based on user-defined criteria such as date range, region, polarization, orbit direction, and minimum coverage percentage. It groups the results, filters groups with a minimum number of images, generates temporal distribution plots, and saves results to text files.

The script uses the `asf_search` library to query the ASF API and performs geometric calculations for coverage using `shapely` and `geopandas`. It includes retry mechanisms for network errors and user-friendly error messages.

## Prerequisites
- **Python Version**: Python 3.8 or higher.
- **Required Libraries**: The script depends on the following Python libraries. Install them using pip:
  ```
  pip install asf_search geopandas matplotlib numpy shapely
  ```
  Note: `geopandas` may require additional system dependencies like GDAL. On Ubuntu, install with `sudo apt install libgdal-dev`. On Windows/macOS, refer to the geopandas documentation.

- **ASF Account**: You need a free account from Earthdata Login (https://urs.earthdata.nasa.gov) to access ASF data. Provide your username and password in the config file.

- **No Internet Restrictions**: The script queries the ASF API, so ensure your network allows access to https://api.daac.asf.alaska.edu.

## Installation
1. Clone or download the script files: `sentinel_search_asf.py` and `config_sentinel_search_asf.txt`.
2. Install the required libraries as mentioned above.
3. Place the config file in the same directory as the script.

## Configuration
Edit the `config_sentinel_search_asf.txt` file to set your parameters:

- **[Credentials]**: Enter your ASF username and password here. These are required and must be provided directly in the file (no environment variables).
- **[General]**: Set data_source to 'asf', start_date and end_date in YYYY-MM-DD, min_images (positive integer, default 10), coverage_percent (0-100, default 100).
- **[Region]**: Define the search region. Set region_type to one of: bounding_box, point_buffer, shapefile, geojson, kml, kmz. Only fill the relevant field; others can be left blank.
  - For bounding_box: Provide lon_min, lat_min, lon_max, lat_max (e.g., 51.0438, 35.5146, 51.6138, 35.8958).
  - For point_buffer: Provide center_lon, center_lat, radius_km (e.g., 51.3515, 35.7053, 15).
  - For shapefile/geojson/kml/kmz: Place the file in the region_folder (default: study_area) and specify the filename if not the default.

If the config file is missing, the script creates a default one.

## How to Run
1. Ensure the config file is set up correctly.
2. Run the script from the command line:
   ```
   python sentinel_search_asf.py
   ```
3. The script will:
   - Read the config.
   - Search for images with retries on network errors (up to 3 attempts with 5-second delays).
   - Filter and group results.
   - Save results to `sentinel/search_results_asf.txt`.
   - Save temporal plots to `sentinel/plots/`.
   - Log details to `sentinel/search.log`.

If no groups meet the min_images criteria, it will warn you. Check the logs for errors.

## Code Explanation
The script is structured as follows:

- **setup_logging()**: Initializes logging to console and file.
- **create_default_config()**: Creates a default config if missing.
- **read_config()**: Parses the config file, validates inputs, and raises user-friendly errors with instructions.
- **point_buffer_to_polygon()**: Converts point-buffer to a polygon geometry.
- **plot_temporal()**: Generates and saves temporal distribution plots using matplotlib.
- **calculate_coverage_percent()**: Computes image coverage over the region using shapely.
- **search_images_asf()**: Main search function. Splits date range into 180-day chunks, queries ASF API with retries for network issues, filters by coverage, and logs raw responses.
- **process_and_plot_groups()**: Groups results by keys (full and simple), writes to file, and calls plotting.
- **main()**: Entry point. Loads config, prepares region geometry, runs search, handles outputs and errors.

Error handling is improved: All exceptions provide actionable advice (e.g., "Please add 'username' to the config file").

## References and Official Resources
For more on ASF Sentinel-1 search:
- ASF Search API Keywords & Endpoints: https://docs.asf.alaska.edu/api/keywords/
- asf_search Python Package Basics: https://docs.asf.alaska.edu/asf_search/basics/
- Search API Basics: https://docs.asf.alaska.edu/api/basics/
- ASF SAR Data Search Manual - Keywords: https://docs.asf.alaska.edu/asf_search/searching/
- asf_search Best Practices: https://docs.asf.alaska.edu/asf_search/BestPractices/
- NASA Earthdata Sentinel-1 Page: https://www.earthdata.nasa.gov/data/platforms/space-based-platforms/sentinel-1
- GitHub Repository for asf_search: https://github.com/asfadmin/Discovery-asf_search (if available; check for updates).

These resources provide detailed documentation on API usage, keywords, and best practices for searching Sentinel-1 data.

## Troubleshooting
- Check `sentinel/search.log` for detailed errors.
- Common issues: Invalid config (e.g., missing password), network problems (retries will attempt to fix), or no results (adjust date range or coverage_percent).
- If plots fail, ensure matplotlib is installed correctly.