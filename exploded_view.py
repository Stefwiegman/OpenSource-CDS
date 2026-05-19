"""Blender exploded-view generator for MAIN_ASSEMBLY (Onshape glTF import).

Run inside Blender's Scripting workspace. Reads all mesh-descendants of the
target collection/object, then keyframes a radial explode animation.

Safe to re-run: clears prior keyframes on these objects before rebuilding.
"""

import bpy
from mathutils import Vector

# ============================ CONFIG ============================
ASSEMBLY_NAME   = "MAIN_ASSEMBLY"   # name of the parent object OR collection
EXPLODE_FACTOR  = 1.8               # 1.0 = doubles distance from centroid; 2.0 = triples it
FRAME_START     = 1
FRAME_HOLD_IN   = 10                # frames showing assembled view before motion starts
EXPLODE_DURATION = 80               # frames each part takes to travel out
STAGGER_SPREAD  = 60                # total spread between first & last part starting
FRAME_HOLD_OUT  = 40                # frames to hold fully-exploded view at the end
SORT_ORDER      = 'OUTER_FIRST'     # 'OUTER_FIRST' | 'INNER_FIRST' | 'NAME' | 'NONE'
EASING          = 'BEZIER'          # 'BEZIER' (smooth) | 'LINEAR'
RESET_FIRST     = True              # wipe existing keyframes on these parts
# ================================================================


def get_descendants(obj):
    out = []
    for child in obj.children:
        out.append(child)
        out.extend(get_descendants(child))
    return out


def find_target_meshes():
    """Resolve ASSEMBLY_NAME to a flat list of mesh objects."""
    if ASSEMBLY_NAME in bpy.data.collections:
        coll = bpy.data.collections[ASSEMBLY_NAME]
        return [o for o in coll.all_objects if o.type == 'MESH']
    if ASSEMBLY_NAME in bpy.data.objects:
        root = bpy.data.objects[ASSEMBLY_NAME]
        if root.type == 'MESH':
            return [root] + [o for o in get_descendants(root) if o.type == 'MESH']
        return [o for o in get_descendants(root) if o.type == 'MESH']
    # Fallback: every mesh in the scene
    return [o for o in bpy.context.scene.objects if o.type == 'MESH']


def world_centroid(obj):
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    return sum(corners, Vector()) / 8.0


def iter_fcurves(action):
    """Yield FCurves from an Action across Blender API versions.

    Blender 4.3 and earlier: action.fcurves is a direct collection.
    Blender 4.4+ (slotted actions): fcurves live under layers > strips > channelbags.
    """
    legacy = getattr(action, "fcurves", None)
    if legacy is not None:
        for fc in legacy:
            yield fc
        return
    for layer in getattr(action, "layers", []):
        for strip in getattr(layer, "strips", []):
            for cb in getattr(strip, "channelbags", []):
                for fc in cb.fcurves:
                    yield fc


def build_exploded_view():
    meshes = find_target_meshes()
    if not meshes:
        print(f"[ABORT] No mesh objects found under '{ASSEMBLY_NAME}'.")
        return

    # World-space centroids
    centroids = {o.name: world_centroid(o) for o in meshes}
    assembly_c = sum(centroids.values(), Vector()) / len(centroids)

    # Per-part explode data
    data = []
    for o in meshes:
        direction = centroids[o.name] - assembly_c
        if direction.length < 1e-6:
            direction = Vector((0.0, 0.0, 1.0))  # parts exactly at center → push up
        distance = direction.length
        world_offset = direction.normalized() * distance * EXPLODE_FACTOR

        # Convert world-space offset to local (parent) space so obj.location keyframes are correct
        if o.parent:
            local_offset = o.parent.matrix_world.inverted().to_3x3() @ world_offset
        else:
            local_offset = world_offset

        data.append({
            'obj': o,
            'dist': distance,
            'local_offset': local_offset,
            'orig_loc': o.location.copy(),
        })

    # Sort for staggering
    if SORT_ORDER == 'OUTER_FIRST':
        data.sort(key=lambda d: -d['dist'])
    elif SORT_ORDER == 'INNER_FIRST':
        data.sort(key=lambda d: d['dist'])
    elif SORT_ORDER == 'NAME':
        data.sort(key=lambda d: d['obj'].name)

    # Wipe previous animation on these parts
    if RESET_FIRST:
        for d in data:
            if d['obj'].animation_data:
                d['obj'].animation_data_clear()

    # Default interpolation for new keyframes — set once, applies during insert
    prev_interp = bpy.context.preferences.edit.keyframe_new_interpolation_type
    bpy.context.preferences.edit.keyframe_new_interpolation_type = EASING

    n = len(data)
    for i, d in enumerate(data):
        obj = d['obj']
        # Per-part timing
        if n > 1 and STAGGER_SPREAD > 0:
            start_offset = int(round((i / (n - 1)) * STAGGER_SPREAD))
        else:
            start_offset = 0
        f_start = FRAME_START + FRAME_HOLD_IN + start_offset
        f_end   = f_start + EXPLODE_DURATION

        # Assembled keyframe
        obj.location = d['orig_loc']
        obj.keyframe_insert(data_path="location", frame=f_start)

        # Exploded keyframe
        obj.location = d['orig_loc'] + d['local_offset']
        obj.keyframe_insert(data_path="location", frame=f_end)

        # Reset viewport to assembled position (so frame 1 shows it together)
        obj.location = d['orig_loc']

    # Ease-in-out flag still needs per-keyframe touch (only meaningful for BEZIER)
    if EASING == 'BEZIER':
        for d in data:
            ad = d['obj'].animation_data
            if not ad or not ad.action:
                continue
            for fc in iter_fcurves(ad.action):
                for kp in fc.keyframe_points:
                    kp.easing = 'EASE_IN_OUT'

    # Restore the user's previous keyframe-interpolation preference
    bpy.context.preferences.edit.keyframe_new_interpolation_type = prev_interp

    # Scene frame range
    total_end = FRAME_START + FRAME_HOLD_IN + STAGGER_SPREAD + EXPLODE_DURATION + FRAME_HOLD_OUT
    scene = bpy.context.scene
    scene.frame_start = FRAME_START
    scene.frame_end = total_end
    scene.frame_current = FRAME_START

    print("=" * 60)
    print(f"Exploded view built")
    print(f"  Parts animated   : {n}")
    print(f"  Assembly center  : ({assembly_c.x:.3f}, {assembly_c.y:.3f}, {assembly_c.z:.3f})")
    print(f"  Explode factor   : {EXPLODE_FACTOR}")
    print(f"  Frame range      : {FRAME_START}  ->  {total_end}")
    print(f"  Stagger order    : {SORT_ORDER}")
    print("=" * 60)
    print("Press SPACE in the 3D viewport to play.")


if __name__ == "__main__":
    build_exploded_view()
