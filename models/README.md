# Models

| File | What it is | LOD |
|---|---|---|
| `000473_A_v2.qif` | MBD: B-rep + PMI, no results | 1.5 |
| `000454_D_v2.qif` | MBD: B-rep + PMI, no results | 2.0 |
| `000473_A-MV-FH.qif` | the same part **measured**, 15 parts, 27% FAIL: the 8-hole position pattern fails on every part | 1.5 |
| `000454_D-MV-FH-2.qif` | the same part **measured**, 15 parts, 17% FAIL, the demo file | 2.0 |

`MV` is measured values, `FH` feature hits (the CMM probe points). The `-MV-FH` files are complete self-contained QIF documents: B-rep geometry, PMI **and** results together, with their own `QPId`s distinct from the `_v2` files. That is why the mesher runs on them directly and the results join to the mesh without crossing documents.

LOD (the mesher's level of detail) is chosen per model, by eye, and cannot be derived from the file. The values are in `qifkit.LOD`.

## Acknowledgments

A big thanks to the [Digital Enterprise Center at Purdue Polytechnic](https://polytechnic.purdue.edu/digital-enterprise-center) for providing the parts used in this workshop.
