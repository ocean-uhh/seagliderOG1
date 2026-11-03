.. _phase:

How the phase is assigned
=========================

``PHASE`` says what the glider was doing at each sample, in the `OG1 phase vocabulary
<https://github.com/OceanGlidersCommunity/OG-format-user-manual/blob/main/vocabularyCollection/phase.md>`_.
The converter assigns it from what the Seaglider recorded it did — its state table and its
guidance-and-control (G&C) events — with GPS fixes for the surface and pressure as the last
fallback. This page states the algorithm, its fallbacks, and shows it on the bundled samples.

What a Seaglider dive looks like
--------------------------------

A Seaglider repeats one cycle per dive file (SGX manual, §2.2.3 *Run phases*):

=============== ======================================================================= ===============
Seaglider phase what happens                                                            OG1 ``PHASE``
=============== ======================================================================= ===============
surface         GPS fix, communications, a second GPS fix                               3 surfacing
start of dive   bleeds oil at the surface, nose full down, until ``$D_FLARE``           7 transition
dive            pitched to the dive angle at ``$D_FLARE``; sinks under G&C              2 descent
apogee          at the target depth, pitch to the apogee angle and VBD to zero          5 inflection
start of climb  pumps oil and pitches up, but still sinking to its deepest point        7 transition
climb           rises to ``$D_SURF``, then coasts to the surface                        1 ascent
=============== ======================================================================= ===============

The CTD samples from the start of the dive to the end of the coast; the surface interval is
booked to the dive file that ends with it. ``PHASE`` 4 (parking) and 6 (propelled) are not
assigned.

The algorithm
-------------

Per dive file, in this order.

**Step 1 — descent, inflection and ascent**, from the first of these signals the file has:

#. **The state table** (``gc_state_state``; basestation 2.10 and later). Each state sets the
   phase from its time until the next state's time:

   ====== ============================ ==============
   code   state                        ``PHASE``
   ====== ============================ ==============
   0, 1   begin dive, end dive         2 descent
   4, 5   begin apogee, end apogee     5 inflection
   2, 3   begin climb, end climb       1 ascent
   8      begin surface coast          1 ascent
   9      end surface coast            3 surfacing
   14, 15 begin surface, end surface   3 surfacing
   ====== ============================ ==============

   States written at the same second (end apogee and begin climb, for example) keep the
   order the file wrote them. Basestation 2.10 writes 8 and 9 for the surface as well; an 8
   straight after a 9 is the surface. A code not in the table leaves its samples at 0
   (unknown) and is logged as a WARNING. The last state runs to the end of the dive file,
   so a file cut off mid-dive keeps that state's phase to its end (sg271 dive 1 ends in the
   apogee).

   The codes' meanings were read from the data: every dive with a state table writes them in
   the same order, "end dive" carries the end-of-phase code for the target depth and "end
   climb" the one for ``$D_SURF``, and "begin apogee" and "end apogee" fall at the start and
   end of the G&C event that moves the VBD to zero.
#. **The G&C events** (``gc_st_secs``, ``gc_end_secs``, ``gc_vbd_ctl``), for files with no state
   table (basestation 2.8). The inflection is the first G&C event that moves the VBD to zero
   after the dive's bleed; descent before it, ascent after. Where a file has both, this event
   is where the state table's apogee falls.
#. **Pressure**, for files with neither: descent up to and including the pressure maximum,
   ascent after. No inflection is assigned.

**Step 2 — transition at the start of the dive.** Descent up to the *last* sample shallower
than ``$D_FLARE`` (``log_D_FLARE``, compared with ``DEPTH``) before the inflection is 7
(transition): the glider is still bleeding at the surface, nose full down, and has not yet
pitched to the dive angle. The last such sample is used, not the first deeper one, because a
glider can sink past ``$D_FLARE`` and come back above it before the dive proper starts (on
one test dive, to 7 m and back up to 3 m with ``$D_FLARE`` at 3 m). A file
without ``log_D_FLARE`` gets no transition here.

**Step 3 — transition at the bottom.** Ascent from the end of the inflection up to and
including the deepest sample (the pressure maximum) is 7 (transition): the apogee has ended
and the glider is pumping and pitching up, but it is still sinking. On the samples the deepest
sample falls after "end apogee" on about half the dives; where it falls inside the inflection,
there is no transition here. Dives assigned from pressure alone have no inflection and no
transition here.

*Possible refinement (not implemented):* hold the transition until the glider first rises at
its usual climbing rate rather than only to the deepest sample — for example, until the rise
rate (−dP/dt) first reaches the 25th percentile of the rise rates from the end of the apogee
to the start of surfacing.

**Step 4 — surfacing.** Every row at a GPS fix time is 3 (surfacing). The converter writes
each fix as rows of their own (``TIME_GPS``, ``LATITUDE_GPS``, ``LONGITUDE_GPS``).

A sample no step claims is 0 (unknown). ``log_D_FLARE`` is the only piloting command used:
``log_D_TGT``, ``log_D_SURF`` and ``log_LOITER_*`` say what the glider was told to do, not what
it did, and are drawn on the figures for comparison only.

In the file
-----------

``PHASE`` (byte, ``_FillValue`` 0) carries:

``phase_vocabulary``
   The OG1 phase vocabulary (linked above).
``flag_values``, ``flag_meanings``
   ``0 1 2 3 4 5 6 7`` and ``unknown ascent descent surfacing parking inflection propelled
   transition``.
``phase_calculation_method``
   Which signal assigned which dives, and on which dives each transition was set, for
   example "From the glider's state table (gc_state_state) on dives 1-3. Descent before the
   last sample above $D_FLARE (log_D_FLARE) is transition (dives 1-3). …".
``phase_calculation_method_vocabulary``
   Empty: OG1 has no vocabulary for methods yet.

``PHASE_QC`` is 0 (no QC performed) on every row: the phase is not quality controlled. Its
``flag_values`` and ``flag_meanings`` are the OG1 scale 0–4.

The conversion page shows the same figures as below for the complete dive nearest the middle
of the mission (section *Phase*).

The figures
-----------

Each dive figure has four panels on one time axis: pressure, each sample colored by its
``PHASE``, with the commanded depths dashed; pitch; the state table as a step line, or the
G&C events' VBD setting when the file has no state table (dotted lines mark the start of each
G&C event); and ``PHASE`` as a band, each color held until the next row. Here the band is
drawn twice: the algorithm above (new), and the rule converters before 0.3.0 used (old:
descent to the pressure maximum, ascent after). Vertical green lines are GPS fixes.

sg271 dive 3 (basestation 3.0.6, state table):

.. image:: _static/phase/dive_sg271.png
   :alt: sg271 dive 3: pressure, pitch, state table and PHASE, new and old

sg005 dive 1 (basestation 2.8, G&C events):

.. image:: _static/phase/dive_sg005.png
   :alt: sg005 dive 1: pressure, pitch, G&C VBD settings and PHASE, new and old

Every dive's share of rows in each phase; the digits above each bar are the dive's phases in
the order they run. A complete dive reads ``3725713``, or ``372513`` when the deepest sample falls inside the
inflection; sg271 dive 1 ends in the apogee.

.. image:: _static/phase/fractions_sg271.png
   :alt: Per-dive share of rows in each phase, sg271

.. image:: _static/phase/fractions_sg005.png
   :alt: Per-dive share of rows in each phase, sg005

Pitch against the rate of pressure change, colored by phase, every dive. Descent sits at
negative pitch and positive dP/dt, ascent at positive pitch and negative dP/dt; inflection
lies between them; transition sits at steep negative pitch with dP/dt near zero (the start
of the dive) and at positive pitch with dP/dt still positive (the bottom). Basestation 3
records pitch and pressure on different rows, so sg271's pitch is interpolated in time onto
the pressure rows.

.. image:: _static/phase/pitch_dpdt.png
   :alt: Pitch against dP/dt colored by phase for sg271 and sg005

The figures are drawn by ``docs/generate_phase_figures.py`` on every docs build, with the
functions in :mod:`seagliderOG1.reports.phase` that the conversion page uses.

Sources
-------

* SGX documentation 2024 v1.0, §2.2.3 *Run phases*,
  `iop.apl.washington.edu <https://iop.apl.washington.edu/iopsg/SGX_documentation_2024-v1.0.pdf>`_.
* Seaglider File Formats Manual: the ``$STATE`` and ``$GC`` lines of the log file.
* `OG1 format <https://oceangliderscommunity.github.io/OG-format-user-manual/OG_Format.html>`_:
  the ``PHASE`` and ``PHASE_QC`` variables.
