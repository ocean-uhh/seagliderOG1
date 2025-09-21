About seagliderOG1
==================

The ``seagliderOG1`` package converts `Seaglider <https://apl.uw.edu/project/project.php?id=seaglider>`_ basestation files (``*.nc``) into `OG1 format <https://oceangliderscommunity.github.io/OG-format-user-manual/OG_Format.html>`_ for standardized oceanographic glider data exchange.

Purpose
-------

Seaglider data is originally produced in a proprietary basestation format that varies between deployments and has evolved over time. The Ocean Gliders community has developed the **OG1 (Ocean Gliders 1)** format as a standardized, CF-compliant format for sharing glider data.

This package bridges that gap by:

* Converting individual dive-climb cycle files into mission-level datasets
* Standardizing variable names, units, and metadata
* Enriching data with sensor information and calibration metadata
* Ensuring CF and OG1 compliance for data interoperability

Format Transformation
--------------------

Major Changes from Basestation to OG1
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Data Structure**

* **Input**: Individual files per dive-climb cycle (``pSSSDDDD_YYYYMMDD.nc``)
* **Output**: Single trajectory file per mission with all cycles concatenated
* **Dimension**: ``sg_data_point`` → ``N_MEASUREMENTS`` (standardized dimension name)

**Variable Standardization**

The conversion process transforms variable names to follow OG1 conventions:

.. code-block:: text

   Basestation → OG1
   ────────────────────
   latitude    → LATITUDE
   longitude   → LONGITUDE  
   ctd_time    → TIME
   gps_lat     → LATITUDE_GPS
   gps_lon     → LONGITUDE_GPS
   eng_pitchAng → PITCH
   eng_rollAng → ROLL
   ctd_depth   → DEPTH

**Metadata Enrichment**

* **Sensor Information**: Automatically detects and catalogs sensors (CTD, oxygen, fluorometers)
* **Calibration Data**: Extracts and preserves sensor calibration coefficients
* **Global Attributes**: Adds CF-compliant and OG1-required global metadata
* **QC Variables**: Creates quality control flag variables following OG1 standards

**GPS Data Integration**

GPS fixes are interpolated onto the main measurement time vector to provide:

* ``LATITUDE_GPS`` and ``LONGITUDE_GPS`` at measurement times
* ``TIME_GPS`` for GPS fix timestamps
* Proper handling of surface intervals and data gaps

**Units and Standards**

* **Unit Conversion**: Automatic conversion to OG1 preferred units (e.g., cm/s → m/s)
* **CF Compliance**: All variables include standard_name, long_name, and units attributes
* **Vocabulary Control**: Uses controlled vocabularies from `NERC <http://vocab.nerc.ac.uk/>`_

Configuration-Driven Approach
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The conversion process is highly configurable through YAML files:

* ``OG1_var_names.yaml``: Variable name mappings
* ``OG1_vocab_attrs.yaml``: CF-compliant variable attributes  
* ``OG1_sensor_attrs.yaml``: Sensor-specific metadata
* ``OG1_global_attrs.yaml``: Global attribute templates

This design allows easy adaptation to new Seaglider formats or OG1 specification updates.

OG1 Format Compliance
---------------------

The output files comply with:

* `OG1 Format Specification <https://oceangliderscommunity.github.io/OG-format-user-manual/OG_Format.html>`_
* `CF Conventions <http://cfconventions.org/>`_ (version 1.10)
* `ACDD Conventions <https://wiki.esipfed.org/Attribute_Convention_for_Data_Discovery>`_ for data discovery

Key OG1 features implemented:

* **Trajectory Format**: Each file represents a single glider trajectory
* **Standardized Variables**: Core oceanographic variables with controlled vocabularies
* **Sensor Metadata**: Detailed sensor information and calibration data
* **Quality Control**: QC flag variables for all measurements
* **Global Attributes**: Rich metadata for data discovery and citation

Quality Assurance
-----------------

The package includes extensive validation:

* **Dimension Checking**: Ensures proper N_MEASUREMENTS dimension
* **Coordinate Validation**: Verifies required coordinates are present  
* **Unit Conversion**: Validates unit compatibility before conversion
* **Metadata Completeness**: Checks for required OG1 attributes

Extended Variables
------------------

Beyond standard OG1 variables, the package preserves:

* **Flight Model Variables**: Vertical and horizontal velocities from glider flight modeling
* **Engineering Data**: Detailed glider state information
* **Derived Variables**: Additional oceanographic parameters when available

For more details on the OG1 format, see the `Ocean Gliders Community documentation <https://oceangliderscommunity.github.io/>`_.

Example Workflow
----------------

A typical conversion processes multiple basestation files:

.. code-block:: python

   from seagliderOG1 import readers, convertOG1, writers
   
   # Load all basestation files from a mission
   datasets = readers.load_basestation_files("path/to/mission/files/")
   
   # Convert to OG1 format (concatenates all dives)
   og1_dataset, variables = convertOG1.convert_to_OG1(datasets)
   
   # Save standardized trajectory file
   writers.save_dataset(og1_dataset, "sg015_mission_001_delayed.nc")

This transforms dozens of individual dive files into a single, standardized trajectory file ready for scientific analysis and data sharing.