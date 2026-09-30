"""The workshop's QIF toolkit: every helper the notebooks share, in one file.

This is meant to be read, not just imported. Notebook 00 walks through it
piece by piece; the later notebooks import from it and say which part they use.

A QIF document is XML, so the toolkit is the standard library's ElementTree plus
numpy and pandas. The work is in knowing which elements point at which.

    Section 1  Opening a document    load, text, the id index
    Section 2  The join              entity_ids, tolerance
    Section 3  Measured results      serial_number, measurement_table, set_aside
    Section 4  Probe points          point_set, measured_features
    Section 5  Geometry and 3D       tessellate, start_viewer, show

Every function takes the document as an argument, rather than reading globals
from whichever notebook imported it. The one module-level constant is the XML
namespace, which never changes.

pyvista is imported only inside the section 5 functions. The notebooks that
draw no 3D view never load VTK, so they still work on a machine where it is
broken.
"""

import base64
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


# =============================================================================
# Section 1. Opening a document
# =============================================================================

# Every QIF element lives in this namespace. ElementTree makes you spell it out
# in each search, so searches read 'qif:Name' and pass NS as the prefix map.
NS = {'qif': 'http://qifstandards.org/xsd/qif3'}

# The sample files ship in models/, one level up from this file. Resolving from
# here, rather than from the current directory, means it works whichever folder
# Jupyter was started in.
MODELS = Path(__file__).resolve().parent.parent / 'models'

# How finely to tessellate each model. LOD is chosen per model by eye and cannot
# be derived from the file.
LOD = {
    '000473_A_v2': 1.5,
    '000473_A-MV-FH': 1.5,
    '000454_D_v2': 2.0,
    '000454_D-MV-FH-2': 2.0,
}


@dataclass
class Doc:
    # One parsed QIF document.
    model: str   # file name without .qif, e.g. '000454_D-MV-FH-2'
    path: Path   # where it was read from
    root: ET.Element
    by_id: dict  # id attribute -> element, for every element that has one


def load(model):
    # Parse a model from models/ and index it by id.
    #
    # QIF is a web of references: a measurement names its characteristic by id,
    # the characteristic names its feature by id, and so on down to the face.
    # Following any of those links means finding an element by its id. Searching
    # the whole tree each time would rescan a multi-megabyte document for every
    # hop, so index every element that carries an id once, up front. After that
    # each hop is a dictionary lookup.
    path = MODELS / f'{model}.qif'
    root = ET.parse(path).getroot()
    by_id = {el.get('id'): el for el in root.iter() if el.get('id') is not None}
    return Doc(model=model, path=path, root=root, by_id=by_id)


def text(el, path):
    # Text of a child element, or None.
    #
    # Accepts None for `el` on purpose. A chain of lookups such as
    # text(doc.by_id.get(some_id), './qif:Name') then yields None when any link
    # is missing, instead of raising halfway along.
    found = None if el is None else el.find(path, NS)
    return None if found is None else (found.text or '').strip()


def linear_unit(doc):
    # The document's length unit, e.g. 'mm', or '' if it does not say.
    return text(doc.root, './qif:FileUnits/qif:PrimaryUnits/qif:LinearUnit/qif:UnitName') or ''


def serial_key(serial):
    # Sort key for serials like 'SN#12', so SN#2 comes before SN#10.
    return int(serial.split('#')[1])


# =============================================================================
# Section 2. The join
#
# A tolerance on the drawing reaches a face of the part through a chain of ids:
#
#   CharacteristicNominal --CharacteristicDefinitionId--> CharacteristicDefinition
#                         --FeatureNominalIds-----------> FeatureNominal
#   FeatureNominal        --EntityInternalIds-----------> face id (== qif_id)
#
# The face id at the end is the same number the mesher stamps on every triangle
# as `qif_id`, which is how anything read from the XML ends up on the 3D part.
# =============================================================================

def entity_ids(doc, feature_nominal_id, seen=None):
    # Geometry entity (face) ids under a feature nominal, recursing into groups.
    #
    # Features nest: a pattern of holes is a feature whose members are themselves
    # features, and only the innermost ones name faces. So this has to recurse.
    # `seen` guards against a document that points a group back at itself.
    #
    # A dangling reference (an id nothing in the document carries) yields no
    # faces rather than an error. Real exports have them.
    seen = set() if seen is None else seen
    if feature_nominal_id in seen:
        return []
    seen.add(feature_nominal_id)

    feature_nominal = doc.by_id.get(feature_nominal_id)
    if feature_nominal is None:
        return []

    ids = [i.text for i in feature_nominal.findall('./qif:EntityInternalIds/qif:Id', NS)]
    for member in feature_nominal.findall('./qif:FeatureNominalIds/qif:Id', NS):
        ids.extend(entity_ids(doc, member.text, seen))
    return ids


def tolerance(definition):
    # (low, high) offsets from nominal, or None where nothing is toleranced.
    #
    # Two shapes. A dimensional characteristic (a diameter, a width) carries
    # Tolerance/MaxValue and MinValue as signed offsets either side of the
    # nominal. A geometric one (flatness, position) carries a single
    # ToleranceValue, which is a zone: its measured value is already a
    # deviation, so the band runs from zero.
    if definition is None or definition.find('./qif:NonTolerance', NS) is not None:
        return None

    single = text(definition, './qif:ToleranceValue')
    if single is not None:
        return (0.0, float(single))

    high = text(definition, './qif:Tolerance/qif:MaxValue')
    low = text(definition, './qif:Tolerance/qif:MinValue')
    if high is None or low is None:
        return None
    if float(high) - float(low) <= 0:
        # A basic dimension written as Max == Min == 0 by an exporter that did
        # not emit NonTolerance. That is a zero band, not an infinitely tight one.
        return None
    return (float(low), float(high))


def tolerance_range(definition):
    # How wide the band is, or None. Notebook 01 only asks "how tight", so the
    # two offsets collapse to their difference; the results table keeps them
    # apart, because which side a value went out on matters there.
    band = tolerance(definition)
    return None if band is None else band[1] - band[0]


# =============================================================================
# Section 3. Measured results
#
# A measurement reaches geometry by a longer route than a tolerance does:
#
#   CharacteristicMeasurement --CharacteristicItemId--> CharacteristicItem
#   CharacteristicItem --CharacteristicNominalId--> CharacteristicNominal (callout)
#                      --FeatureItemIds---------> FeatureItem
#   FeatureItem        --FeatureNominalId-------> FeatureNominal --> face ids
#
# The detour through the item matters. A callout such as a hole diameter applied
# to four holes is one CharacteristicNominal, listing all four features. Each
# hole's measurement belongs to one CharacteristicItem, which names just its own
# hole. Through the nominal, every measurement maps to all four holes.
# =============================================================================

def serial_number(doc, measurement_results, measurement):
    # Serial of the part a measurement belongs to.
    #
    # The two sample parts record this two valid ways. 000454_D hangs
    # ActualComponentIds off each MeasurementResults; 000473_A omits that and
    # puts an ActualComponentId on every individual measurement instead. Try
    # both.
    for component_id in (text(measurement_results, './qif:ActualComponentIds/qif:Id'),
                         text(measurement, './qif:ActualComponentId')):
        if component_id is not None:
            serial = text(doc.by_id.get(component_id), './qif:SerialNumber')
            if serial:
                return serial
    return None


def fraction_of_band(row):
    # Signed share of the tolerance band a measurement consumed.
    #
    # 0 is on nominal, +/-1.0 exactly on a limit, beyond that out of tolerance.
    # It puts characteristics with different nominals and tolerances on one axis.
    if pd.isna(row['value']) or pd.isna(row['high']):
        return None
    deviation = row['value'] - (0.0 if pd.isna(row['nominal']) else row['nominal'])
    limit = row['high'] if deviation >= 0 else abs(row['low'])
    if limit > 0:
        return deviation / limit

    # A closed side. A one-sided band such as +0.35/-0 allows no deviation at all
    # in one direction, so any deviation that way is out of tolerance by
    # definition, and dividing by the zero distance to that limit would say nothing
    # instead. Score it past the limit by how far it went, in band widths.
    return float(np.copysign(1 + abs(deviation) / (row['high'] - row['low']), deviation))


def measurement_table(doc):
    # One row per CharacteristicMeasurement: one application of a callout, on
    # one part. Nothing is filtered out here; see set_aside for that.
    #
    # Columns:
    #   serial          which part (SN#1...)
    #   characteristic  the CharacteristicItem's name: one application
    #   name            the CharacteristicNominal's name: the callout
    #   type            Diameter, Position, Flatness...
    #   nominal         target value; None for geometric tolerances
    #   low, high       tolerance offsets from nominal (see tolerance)
    #   value           what the CMM reported
    #   status_from_file  the status the file records: PASS, FAIL or UNDEFINED
    #   entities        face ids this application covers, as a sorted tuple
    #   fraction        see fraction_of_band
    rows = []
    for results in doc.root.findall('.//qif:MeasurementResults', NS):
        for measurement in results.findall('.//qif:CharacteristicMeasurements/*', NS):
            item = doc.by_id.get(text(measurement, './qif:CharacteristicItemId'))
            nominal = doc.by_id.get(text(item, './qif:CharacteristicNominalId'))
            if nominal is None:
                continue
            definition = doc.by_id.get(text(nominal, './qif:CharacteristicDefinitionId'))

            value = text(measurement, './qif:Value')
            target = text(nominal, './qif:TargetValue')
            band = tolerance(definition)

            # Geometry through the item, not the nominal: the nominal lists every
            # feature the callout covers, the item only the one it was applied to.
            entities = []
            for feature_item_id in item.findall('./qif:FeatureItemIds/qif:Id', NS):
                feature_item = doc.by_id.get(feature_item_id.text)
                entities.extend(entity_ids(doc, text(feature_item, './qif:FeatureNominalId')))

            rows.append({
                'serial': serial_number(doc, results, measurement),
                'characteristic': text(item, './qif:Name'),
                'name': text(nominal, './qif:Name'),
                'type': measurement.tag.split('}')[1].replace('CharacteristicMeasurement', ''),
                'nominal': float(target) if target else None,
                'low': band[0] if band else None,
                'high': band[1] if band else None,
                'value': float(value) if value else None,
                'status_from_file': text(measurement, './qif:Status/qif:CharacteristicStatusEnum'),
                'entities': tuple(sorted(set(entities))),
            })

    table = pd.DataFrame(rows)
    table['fraction'] = table.apply(fraction_of_band, axis=1)
    return table


# A geometric characteristic reading more than this many times its own zone is
# treated as a bad export rather than a bad part. A judgment call, not a fact,
# which is why it is a named constant and set_aside reports what it caught.
SUSPECT_RATIO = 20


def set_aside(measurements, suspect_ratio=SUSPECT_RATIO):
    # Split the table into rows worth charting and three kinds of row that are not.
    #
    # Returns a dict of DataFrames, so the caller can say how many of each went
    # and why, rather than rows vanishing silently:
    #   unmeasured    reported for the part, but with no value
    #   untoleranced  a value, but nothing to judge it against
    #   suspect       a geometric tolerance more than suspect_ratio times its zone
    #   clean         everything else
    #
    # In pandas, isna() means "is missing" and notna() "is present". The quiet
    # alternative is dropna(), which would drop the same rows in one call and
    # hide why each one went.
    unmeasured = measurements[measurements.value.isna()]
    untoleranced = measurements[measurements.value.notna() & measurements.high.isna()]

    # "Geometric" means "has no nominal": flatness, position and the rest measure
    # a deviation directly, so there is no target value. A zero lower limit is not
    # the same test: a one-sided dimension such as +0.2/-0 has one too.
    suspect = measurements[measurements.fraction.notna()
                           & measurements.nominal.isna()
                           & (measurements.fraction > suspect_ratio)]

    dropped = unmeasured.index.union(untoleranced.index).union(suspect.index)
    return {'unmeasured': unmeasured, 'untoleranced': untoleranced,
            'suspect': suspect, 'clean': measurements.drop(index=dropped)}


def label_items(clean):
    # Add a `label` column that tells apart the applications of one callout.
    #
    # One CharacteristicNominal can have many CharacteristicItems, and they all
    # share the nominal's name: four holes under one diameter callout are four
    # rows per part called "Radial Dimension (188)". Grouping by that name would
    # silently merge four physical holes into one. Number them "#1".."#4", and
    # keep the bare name where it is already unique.
    items_per_name = clean.groupby('name').characteristic.nunique()
    item_order = {item: i
                  for name, group in clean.groupby('name')
                  for i, item in enumerate(sorted(group.characteristic.unique()), 1)}
    return clean.assign(label=[name if items_per_name[name] == 1 else f'{name} #{item_order[item]}'
                               for name, item in zip(clean.name, clean.characteristic)])


def results(doc):
    # The cleaned, labeled table in one call: measurement_table, then set_aside,
    # then label_items. Notebook 02 runs those steps one at a time and shows what
    # each does; the notebooks after it start from here.
    return label_items(set_aside(measurement_table(doc))['clean'])


# =============================================================================
# Section 4. Probe points
#
# Besides the values it reported, the CMM wrote down every point it touched.
# Each measured feature points at a point set, stored as base64 binary arrays.
# =============================================================================

def point_set(doc, point_set_id):
    # Decode one point set: surface points, normals, probe radii, compensation.
    #
    # Four parallel binary arrays. The compensation flag and the probe radius are
    # both in the file, so the ball size does not have to be looked up elsewhere.
    element = doc.by_id.get(point_set_id)
    if element is None:
        return None

    def decode(tag, dtype):
        raw = text(element, f'./qif:{tag}')
        return None if raw is None else np.frombuffer(base64.b64decode(raw), dtype=dtype)

    points = decode('BinaryPoints', np.double).reshape(-1, 3)
    normals = decode('BinaryNormals', np.double).reshape(-1, 3)
    radii = decode('BinaryProbeRadii', np.double)
    compensated = decode('BinaryCompensated', bool)

    # Uncompensated points are probe *centers*. Left raw they sit one ball radius
    # off every surface, about 2 mm here.
    surface = points - normals * np.where(compensated, 0.0, radii)[:, None]
    return {'surface': surface, 'normals': normals, 'radii': radii,
            'compensated': compensated}


def measured_features(doc, serial):
    # Probed features for one part, each with its points and the faces it covers.
    #
    # Returns a list of dicts: name, type (Cylinder, Plane...), element (the
    # measured feature's XML, which holds the CMM's fit), entities, points.
    out = []
    seen_geometry = set()
    for results_el in doc.root.findall('.//qif:MeasurementResults', NS):
        for feature in results_el.findall('./qif:MeasuredFeatures/*', NS):
            if serial_number(doc, results_el, feature) != serial:
                continue
            point_set_id = text(feature, './qif:PointList/qif:WholePointSetId')
            if point_set_id is None:
                continue
            item = doc.by_id.get(text(feature, './qif:FeatureItemId'))
            nominal_id = text(item, './qif:FeatureNominalId')
            entities = entity_ids(doc, nominal_id) if nominal_id else []

            # One physical feature can be measured once and recorded twice: a
            # bore carrying both a diameter and a perpendicularity gets a
            # FeatureItem per characteristic, each with its own copy of the same
            # points. Key on the geometry so the bore is counted once.
            key = tuple(sorted(entities)) or text(feature, './qif:FeatureName')
            if key in seen_geometry:
                continue
            seen_geometry.add(key)

            out.append({'name': text(feature, './qif:FeatureName'),
                        'type': feature.tag.split('}')[1].replace('FeatureMeasurement', ''),
                        'element': feature,
                        'entities': entities,
                        'points': point_set(doc, point_set_id)})
    return out


# =============================================================================
# Section 5. Geometry and 3D
# =============================================================================

MESHER_MISSING = (
    'The mesher, qif-brep2mesh, is not installed. It comes with the workshop\n'
    'environment. From the repo root, with the venv active:\n'
    '  pip install -r requirements.lock')


def tessellate(doc, lod=None):
    # Mesh the document's B-rep into a pyvista surface, tagged with qif_id.
    #
    # The mesher returns plain numpy: points, triangles, and one qif_id per
    # triangle naming the QIF face it came from. That id is the join key every
    # 3D view rests on. Meshing the document we parsed, in memory, makes pairing
    # a mesh with the wrong QIF file impossible rather than merely checked.
    #
    # Returns (mesh, arrays): the PolyData with cell_data['qif_id'], and the
    # mesher's raw output, which also carries lod, linear_unit and qpid.
    try:
        from qif_brep2mesh import mesh_document
    except ModuleNotFoundError:
        raise SystemExit(MESHER_MISSING)
    import pyvista as pv

    arrays = mesh_document(str(doc.path), lod=LOD[doc.model] if lod is None else lod)

    # pyvista wants each face prefixed by its vertex count: [3, a, b, c, 3, ...].
    triangles = arrays['triangles']
    faces = np.hstack([np.full((len(triangles), 1), 3, dtype=np.int64), triangles]).ravel()
    mesh = pv.PolyData(arrays['points'], faces)
    mesh.cell_data['qif_id'] = arrays['qif_id']
    return mesh, arrays


async def start_viewer():
    # Switch pyvista to the live 3D viewer and start its server. Call once, near
    # the top, as `await qifkit.start_viewer()`.
    #
    # trame gives a live viewport you can orbit. If the 3D cell stays blank or
    # spins forever, you are probably on a locked-down machine that cannot open
    # the websocket back to the kernel. Call pv.set_jupyter_backend('html') for
    # a static-but-orbitable scene, or 'static' for a plain image.
    #
    # Why start the server here, rather than letting the first plot do it: left
    # to itself, pyvista starts it by patching Python's event loop, and with
    # current Jupyter kernels that patch breaks the kernel: later cells queue up
    # and never run. Awaiting the server up front avoids the patch entirely.
    import pyvista as pv
    from pyvista.trame.jupyter import launch_server

    pv.set_jupyter_backend('trame')
    await launch_server().ready


def show(plotter, fallback_png):
    # Display a plotter in the notebook, with a link to open it in its own tab.
    #
    # A machine with no or broken OpenGL cannot render interactively, so fall
    # back to writing a screenshot next to the notebook.
    from IPython.display import Markdown, display

    try:
        viewer = plotter.show(return_viewer=True,
                              jupyter_kwargs={'width': '100%', 'height': '700px',
                                              'collapse_menu': True})
        display(viewer)
        if getattr(viewer, 'src', None):
            display(Markdown(f'[Open this view in its own browser tab]({viewer.src}) '
                             '(press F11 for full screen).'))
    except Exception as err:
        print(f'interactive render failed ({err}), falling back to a screenshot')
        plotter.screenshot(fallback_png)
