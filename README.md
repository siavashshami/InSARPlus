Overview
- InSARPlus is a free and open-source software designed for InSAR (Interferometric Synthetic Aperture Radar) processing, tailored for students and researchers in Earth sciences and remote sensing. It provides tools for searching, downloading, and processing Sentinel-1 SLC images. Released under the MIT License, users can freely use, modify, and extend the software while preserving the original ownership of Siavash Shami. The project is actively being updated with new features and phases.

Project Status
- The project is under active development with the following phases:
- Phase 1: Search (Complete): Search for Sentinel-1 SLC images using the ASF API. See step_1/sentinel_search_asf for details.
- Phase 2: Download (In Progress): Download selected images.
- Phase 3: Processing (Planned): InSAR processing for geophysical analysis.
- Additional phases to be added.

Getting Started
1. Clone the repository: git clone https://github.com/siavashshami/InSARPlus.git
2. Navigate to step_1/sentinel_search_asf/ and follow its README.md for setup instructions.
3. Install dependencies: pip install asf_search geopandas matplotlib numpy shapely
4. Register at urs.earthdata.nasa.gov for ASF API access.

Contributing
Students and researchers are encouraged to contribute by adding features, improving documentation, or fixing bugs. To contribute:
1. Fork the repository.
2. Create a branch: git checkout -b feature/your-feature.
3. Submit a Pull Request.

License
InSARPlus is licensed under the MIT License, ensuring free use and development while retaining copyright (© 2025 Siavash Shami). See LICENSE for details.

Contact
For questions or collaboration, open an issue on GitHub or contact Siavash Shami.
