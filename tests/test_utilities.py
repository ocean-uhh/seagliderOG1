import pathlib
import sys

script_dir = pathlib.Path(__file__).parent.absolute()
parent_dir = script_dir.parents[0]
sys.path.append(str(parent_dir))

from seagliderOG1 import utilities


def calibcomm():
    """
    Test function for the `utilities._parse_calibcomm` function.
    This function defines a set of test strings with expected calibration dates and serial numbers.
    It then iterates over these test strings, parses them using the `_parse_calibcomm` function,
    and asserts that the parsed results match the expected values.
    Test strings and their expected results:
        - "SBE s/n 0112 calibration 20apr09": ('20090420', '0112')
        - "SBE#29613t1/c1 calibration 7 Sep 02": ('20020907', '29613')
        - "SBE t12/c12 calibration 30DEC03": ('20031230', 'Unknown')
        - "SBE s/n 19, calibration 9/10/08": ('20080910', '19')
        - "SBE 0015 calibration 4/28/08": ('20080428', '0015')
        - "SBE 24520-1 calibration 04FEB08": ('20080204', '24520-1')
        - "SBE 0021 calibration 15sep08": ('20080915', '0021')
        - "SBE s/n 0025, calibration 10 june 08": ('20080610', '0025')
    Asserts:
        - The parsed calibration date matches the expected calibration date.
        - The parsed serial number matches the expected serial number.
    """
    
    test_strings = {"SBE s/n 0112 calibration 20apr09": ('20090420', '0112'),
        "SBE#29613t1/c1 calibration 7 Sep 02": ('20020907', '29613t1c1'),
        "SBE t12/c12 calibration 30DEC03": ('20031230', 't12c12'),
        "SBE s/n 19, calibration 9/10/08": ('20080910', '19'),
        "SBE 0015 calibration 4/28/08": ('20080428', '0015'),
        "SBE 24520-1 calibration 04FEB08": ('20080204', '24520'),
        "SBE 0021 calibration 15sep08": ('20080915', '0021'),
        "SBE s/n 0025, calibration 10 june 08": ('20080610', '0025'),
        "Optode 4330F S/N 182 foil batch 2808F calibrated 09may09": ('20090509', '182'),
        "SBE 43F s/n 25281-1 calibration 12 Aug 01": ('20010812', '25281'),
        "SBE 43F s/n 041 calibration 22JAN04": ('20040122', '041'),
        "SBE 43 s/n F0012 calibration 27 Aug 02": ('20020827', 'F0012'), 
        "0061": ('Unknown', '0061'),
        "SBE 43F s/n 029 calibration 07May07": ('20070507', '029'),
    }

    for calstring, (caldate1, serialnum1) in test_strings.items():
        caldate, serialnum = utilities._parse_calibcomm(calstring, firstrun=False)

        assert caldate == caldate1
        assert serialnum == serialnum1

