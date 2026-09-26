"""SKY130 geometry used by the template generator, in Magic internal units.

One unit is 5 nm (``scalegrid 1 2``). Every value below is the drawn Magic
value from ``sky130A.tech`` (rule name in the comment) or the dimension the
PDK's own ``sky130A.tcl`` PCells draw. Magic's full DRC deck remains the
oracle; these numbers only make the templates correct by construction.
"""

UNITS_PER_UM = 200


def u(um):
    """Micrometres to internal units (5 nm grid)."""
    return int(round(float(um) * UNITS_PER_UM))


def um(units):
    return units / UNITS_PER_UM


def even(value):
    """Round up to an even unit so that centred features stay on the grid."""
    value = int(value)
    return value + (value & 1)


# Front end ------------------------------------------------------------------
CONT = 34  # licon/mcon drawn size 0.17 (licon.1, mcon.1)
DIFF_SURR = 12  # diffusion around its contact, 0.06 in one direction (licon.5c)
REGION = 58  # contacted S/D region 0.29 = 0.06 + 0.17 + 0.06 (PCell diff_extension)
MIN_EFFL = 37  # PCell min_effl 0.185: short multi-finger gates stretch the pitch
ENDCAP = 26  # poly overhang of a transistor 0.13 (poly.8)
POLY_W = 30  # 0.15 (poly.1a)
POLY_SP = 42  # 0.21 (poly.2)
POLY_DIFF = 15  # non-FET poly to diffusion 0.075 (poly.4)
POLY_TAP = 11  # non-FET poly to tap 0.055
PC_DIFF = 38  # poly contact to diffusion 0.19 (licon.14)
PC_PDIFF = 47  # poly contact to P diffusion 0.235 (licon.9 + psdm.5a)
PC_SURR = 16  # poly around poly contact, 0.08 in one direction (licon.8a)
PC_SURR_ALL = 10  # 0.05 all around (licon.8)
DIFF_SP = 54  # diffusion/tap spacing 0.27 (diff/tap.3)
TAP_SURR = 24  # tap around its contact, 0.12 in one direction (licon.7)
TAP_W = 82  # tap strip width: contact plus 0.12 on both sides
LI_W = 34  # 0.17 (li.1)
LI_SP = 34  # 0.17 (li.3)
LI_SURR = 16  # 0.08 in one direction (li.5)
MCON_SP = 38  # 0.19 (mcon.2)

# Wells ----------------------------------------------------------------------
NWELL_SURR = 36  # N-well around P diffusion or N tap 0.18 (diff/tap.8, .10)
NDIFF_NWELL = 68  # N diffusion to N-well 0.34 (diff/tap.9)
PTAP_NWELL = 26  # P tap to N-well 0.13 (diff/tap.11)
NWELL_W = 168  # 0.84 (nwell.1)

# Back end -------------------------------------------------------------------
M1_W, M1_SP = 28, 28  # 0.14 (met1.1, met1.2)
M1_SURR_MCON, M1_SURR_MCON_DIR = 6, 12  # 0.03 / 0.06 (met1.4, met1.5)
V1, V1_SP, V1_SURR = 52, 12, 6  # drawn via1 0.26, spacing 0.06, metal 0.03 directional
M2_W, M2_SP = 28, 28  # 0.14 (met2.1, met2.2)
V2, V2_SP, V2_SURR_M2, V2_SURR_M3 = 56, 24, 9, 5  # via2 0.28; M2 0.045 dir; M3 0.025
M3_W, M3_SP = 60, 60  # 0.30 (met3.1, met3.2)
V3, V3_SP, V3_SURR_M3, V3_SURR_M4 = 64, 16, 6, 1  # via3 0.32
M4_W, M4_SP = 60, 60  # 0.30 (met4.1, met4.2)
WIDE = 601  # metal wider than 3.005 um needs the wide spacing rule (met*.3b)

# MIM capacitor (capm between metal3 and metal4) ------------------------------
MIM_SP = 168  # 0.84 (capm.2a)
MIM_M3_SURR = 28  # metal3 bottom plate around capm 0.14
MIMCC_SURR = 16  # capm around its contact 0.08
MIM_MAX = 6000  # 30 um tiles, as the PCell recommends for accurate models
MIM_FF_PER_UM2 = 2.0
MIM_FF_PER_UM = 0.38  # edge term used by the existing flow (0.19 fF/um per side pair)
