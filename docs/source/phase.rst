.. _phase:

How the phase is assigned
=========================

``PHASE`` says what the glider was doing at each sample, in the `OG1 phase vocabulary
<https://github.com/OceanGlidersCommunity/OG-format-user-manual/blob/main/vocabularyCollection/phase.md>`_.
The converter assigns it from what the Seaglider recorded it did, not from the commands it was
given. This page states the rules and shows them on the bundled samples.

What a Seaglider dive looks like
--------------------------------

A Seaglider repeats one cycle per dive file (SGX manual, §2.2.3 *Run phases*):

=============== ===================================================================== ==============
Seaglider phase what happens                                                          OG1 ``PHASE``
=============== ===================================================================== ==============
surface         GPS fix, communications, a second GPS fix                             3 surfacing
dive            bleeds oil and sinks; regular guidance and control below ``$D_FLARE`` 2 descent
apogee          two G&C cycles: VBD to zero, then pitch and VBD to the climb          5 inflexion
climb           pumps oil and rises to ``$D_SURF``, then coasts to the surface        1 ascent
=============== ===================================================================== ==============

The CTD samples during dive, apogee and climb, and the surface interval is booked to the dive
file that ends with it. ``PHASE`` 4 (parking), 6 (propelled) and 7 (transition) are not assigned.

The rules
---------

Each dive file is assigned by the first of these the file supports:

#. **The state table** (``gc_state_state``, basestation 2.10 and later). Each state sets the
   phase from its time until the next state:

   ===== ============================ ==============
   code  state                        ``PHASE``
   ===== ============================ ==============
   0, 1  begin dive, end dive         2 descent
   4, 5  begin apogee, end apogee     5 inflexion
   2, 3  begin climb, end climb       1 ascent
   8     begin surface coast          1 ascent
   9     end surface coast            3 surfacing
   14,15 begin surface, end surface   3 surfacing
   ===== ============================ ==============

   Basestation 2.10 writes 8 and 9 for the surface as well; an 8 straight after a 9 is the
   surface. A code not in the table leaves its samples at 0 and is logged as a WARNING.
#. **The G&C events** (``gc_st_secs``, ``gc_end_secs``, ``gc_vbd_ctl``), for files with no state
   table (basestation 2.8). The apogee starts with the event that moves the VBD to zero after
   the dive's bleed; descent before it, ascent after.
#. **Pressure**, for files with neither: descent up to the pressure maximum, ascent after.

In every case:

* a row at a GPS fix time is 3 (surfacing);
* the inflexion spans both apogee G&C cycles, so it ends with the event that moves pitch and VBD
  to the climb. The state table starts the climb at that event, but the glider is still turning
  and often reaches its pressure maximum there;
* a sample no rule claims is 0 (unknown);
* the last state runs to the end of the dive file, so a file cut off mid-dive (sg271 dive 1,
  which ends at the apogee) keeps that state's phase to its end.

Commands (``log_D_TGT``, ``log_D_FLARE``, ``log_D_SURF``, ``log_LOITER_*``) are never used to
assign a phase; the figures draw them for comparison.

``PHASE_QC`` says which rule assigned each sample:

===== =============== ===========================================================
flag  meaning         assigned from
===== =============== ===========================================================
1     good            the state table, or a GPS fix
2     probably_good   the G&C events (no state table in the file)
8     estimated       pressure alone
9     missing_value   nothing (``PHASE`` 0)
===== =============== ===========================================================

The figures
-----------

Each dive figure has four panels on one time axis. Pressure, with each sample colored by its
new ``PHASE`` and the commanded depths dashed; pitch; the state table as a step line, or the G&C
events' VBD setting when the file has no state table (dotted lines mark the start of each G&C
event); and ``PHASE``, new above old, each band colored until the next row. Vertical green
lines are GPS fixes. The title gives how many rows change phase.

sg271 dive 3 (basestation 3.0.6, state table):

.. image:: _static/phase/dive_sg271.png
   :alt: sg271 dive 3: pressure, pitch, state table and PHASE, new and old

sg005 dive 1 (basestation 2.8, no state table, G&C events):

.. image:: _static/phase/dive_sg005.png
   :alt: sg005 dive 1: pressure, pitch, G&C VBD settings and PHASE, new and old

Every dive's share of rows in each phase. The digits above each bar are the dive's phases in
the order they run; every complete dive reads ``32513``. sg271 dive 1 ends at the apogee
(``3253``):

.. image:: _static/phase/fractions.png
   :alt: Per-dive share of rows in each phase for sg271 and sg005

Pitch against the rate of pressure change, colored by phase. Descent sits at negative pitch
and positive dP/dt, ascent at positive pitch and negative dP/dt; inflexion lies between them,
where pitch reverses and dP/dt passes through zero. Basestation 3 records pitch and pressure on
different rows, so sg271's pitch is interpolated in time onto the pressure rows:

.. image:: _static/phase/pitch_dpdt.png
   :alt: Pitch against dP/dt colored by phase for sg271 and sg005

The figures are drawn by ``docs/generate_phase_figures.py`` on every docs build.

Sources
-------

* SGX documentation 2024 v1.0, §2.2.3 *Run phases*,
  `iop.apl.washington.edu <https://iop.apl.washington.edu/iopsg/SGX_documentation_2024-v1.0.pdf>`_.
* Seaglider File Formats Manual: the ``$STATE`` and ``$GC`` lines of the log file.
* The OG1 phase vocabulary (linked above).
