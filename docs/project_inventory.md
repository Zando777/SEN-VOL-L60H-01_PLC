# Volvo L60H project inventory

Consolidated on 2026-07-20.

## Canonical source repository

- Local: `/Users/alexandersteffen/Documents/PLC-Course/volvo-l60h-plc`
- GitHub: `Zando777/SEN-VOL-L60H-01_PLC`
- The Git repository is the canonical location for reviewable SCL, Python and
  documentation.

## Active TIA Portal projects on sensmore-s7

Location: `C:\Users\sensmore\Documents\Automation`

| Project | Purpose | Status at consolidation |
|---|---|---|
| `volvo_l60h_main` | Current real-machine production lineage | Keep active; do not replace with I/O-test code |
| `volvo_l60h_io_test` | Commissioning-only independent output and crank testing | Keep active for commissioning |
| `volvo_l60h_io_test_logging_dev` | Isolated PLC event-logging integration for the I/O test | Development only; not downloaded |
| `volvo_l60h_production_dev` | Isolated development/compile target for the new production sequencer | Keep active; not downloaded to the PLC |

The three original active projects retain their matching `.backup` directories
in the Automation root. These contain TIA-generated ZIP recovery copies and
must remain paired with their projects. The logging-development clone was
created separately with Openness `SaveAs`.

## Archived legacy TIA projects

Location:

`C:\Users\sensmore\Documents\Automation\_archive\volvo_l60h_legacy_2026-07-20`

Archived project lineages:

- `volvo_l60h`
- `volvo_l60h_alex`
- `volvo_l60h_alex_pressuresremoved`

Their corresponding `.backup` directories are in the same archive. The archive
contains `manifest.csv` with project modification dates, file counts, sizes and
SHA-256 hashes of the `.ap20` files. Nothing was permanently deleted.

## Archived S7 Desktop exports

Location:

`C:\Users\sensmore\Desktop\_archive\volvo_l60h_exports_2026-07-20`

This contains older Openness exports and ZIPs that previously cluttered the
Desktop. The current production source staging directory remains at:

`C:\Users\sensmore\Desktop\volvo_l60h_production_sources`

## Local loose-file snapshot

The duplicate `volvo_l60h_io_test_snapshot` directory was moved to:

`/Users/alexandersteffen/Documents/PLC-Course/_archive/volvo_l60h_io_test_snapshot_2026-07-20`

Its SCL and GUI files were byte-identical to the canonical Git repository when
archived. It is recovery material only and must not be edited or deployed.

## Naming rule

Do not create another Volvo L60H TIA project without assigning it one of these
roles or updating this inventory. New production work belongs in
`volvo_l60h_production_dev` until it has been reviewed and deliberately promoted
to `volvo_l60h_main`. I/O-test logging work belongs in
`volvo_l60h_io_test_logging_dev` until it has compiled, been reviewed and is
deliberately promoted to `volvo_l60h_io_test`.
