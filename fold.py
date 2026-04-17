bl_info = {
    "name": "Packaging Fold Tool",
    "author": "umtksa",
    "version": (0, 7),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Packaging",
    "description": "Packaging tool with auto-rig from selected base face",
    "category": "Object",
}

import math
import bpy
import bmesh
from collections import deque
from bpy.props import StringProperty, FloatProperty, FloatVectorProperty
from bpy.types import Panel, Operator


# ----------------------
# PROPERTIES
# ----------------------

class PackagingProps(bpy.types.PropertyGroup):
    image_path: StringProperty(name="Front Image", subtype='FILE_PATH')
    inner_image_path: StringProperty(name="Back Image", subtype='FILE_PATH')

    thickness: FloatProperty(name="Thickness (mm)", default=0.5, min=0.0, max=10.0)

    paper_color: FloatVectorProperty(
        name="Paper Color",
        subtype='COLOR',
        size=4,
        default=(0.9, 0.85, 0.75, 1.0),
        min=0.0,
        max=1.0
    )


# ----------------------
# PLANE OPERATOR
# ----------------------

class PACKAGING_OT_create_plane(Operator):
    bl_idname = "packaging.create_plane"
    bl_label = "Generate Plane"

    def execute(self, context):
        props = context.scene.packaging_props

        if not props.image_path:
            self.report({'ERROR'}, "Select front image")
            return {'CANCELLED'}

        img_front = bpy.data.images.load(props.image_path)
        width, height = img_front.size
        aspect = width / height if height != 0 else 1

        bpy.ops.mesh.primitive_plane_add(size=1)
        obj = context.active_object
        obj.scale.x = aspect
        obj.scale.y = 1
        bpy.ops.object.transform_apply(scale=True)

        # FRONT MATERIAL
        mat_front = bpy.data.materials.new(name="FrontMat")
        mat_front.use_nodes = True
        nodes = mat_front.node_tree.nodes
        links = mat_front.node_tree.links
        nodes.clear()
        out = nodes.new("ShaderNodeOutputMaterial")
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = img_front
        links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

        # BACK MATERIAL
        mat_back = bpy.data.materials.new(name="BackMat")
        mat_back.use_nodes = True
        nodes = mat_back.node_tree.nodes
        links = mat_back.node_tree.links
        nodes.clear()
        out = nodes.new("ShaderNodeOutputMaterial")
        bsdf = nodes.new("ShaderNodeBsdfPrincipled")
        if props.inner_image_path:
            img_back = bpy.data.images.load(props.inner_image_path)
            tex_back = nodes.new("ShaderNodeTexImage")
            tex_back.image = img_back
            links.new(tex_back.outputs["Color"], bsdf.inputs["Base Color"])
        else:
            bsdf.inputs["Base Color"].default_value = props.paper_color
        links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])

        # EDGE MATERIAL
        mat_edge = bpy.data.materials.new(name="EdgeMat")
        mat_edge.use_nodes = True
        edge_nodes = mat_edge.node_tree.nodes
        edge_links = mat_edge.node_tree.links
        edge_nodes.clear()
        edge_out = edge_nodes.new("ShaderNodeOutputMaterial")
        edge_bsdf = edge_nodes.new("ShaderNodeBsdfPrincipled")
        edge_bsdf.inputs["Base Color"].default_value = props.paper_color
        edge_links.new(edge_bsdf.outputs["BSDF"], edge_out.inputs["Surface"])

        obj.data.materials.append(mat_front)
        obj.data.materials.append(mat_back)
        obj.data.materials.append(mat_edge)

        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
        bpy.ops.object.mode_set(mode='OBJECT')

        for poly in obj.data.polygons:
            poly.material_index = 0

        bpy.ops.object.mode_set(mode='OBJECT')

        solid = obj.modifiers.new(name="Thickness", type='SOLIDIFY')
        solid.thickness = props.thickness / 1000.0
        solid.offset = 0
        solid.material_offset = 1
        solid.material_offset_rim = 2

        return {'FINISHED'}


# ----------------------
# EDIT OPERATORS
# ----------------------

class PACKAGING_OT_delete_faces(Operator):
    bl_idname = "packaging.delete_faces"
    bl_label = "Delete Selected Faces"

    def execute(self, context):
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.delete(type='FACE')
        return {'FINISHED'}


class PACKAGING_OT_dissolve_faces(Operator):
    bl_idname = "packaging.dissolve_faces"
    bl_label = "Dissolve Selected"

    def execute(self, context):
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.dissolve_faces()
        return {'FINISHED'}


# ----------------------
# AUTO RIG OPERATOR
# ----------------------

class PACKAGING_OT_auto_rig(Operator):
    bl_idname = "packaging.auto_rig"
    bl_label = "Auto Rig from Selected Face"
    bl_description = "Select one base face in Edit Mode, then run this to build the full rig"

    def execute(self, context):
        obj = context.active_object

        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "Select a mesh object")
            return {'CANCELLED'}

        if obj.mode != 'EDIT':
            self.report({'ERROR'}, "Enter Edit Mode and select the base face first")
            return {'CANCELLED'}

        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.verts.ensure_lookup_table()

        selected_faces = [f for f in bm.faces if f.select]
        if len(selected_faces) != 1:
            self.report({'ERROR'}, "Select exactly ONE base face")
            return {'CANCELLED'}

        root_face = selected_faces[0]

        # --------------------------------------------------
        # BFS: traverse all faces from root
        # --------------------------------------------------
        face_data = {}   # face_index -> {parent_face, shared_edge_center, shared_edge_dir}
        visited = set()
        queue = deque()

        root_idx = root_face.index
        face_data[root_idx] = {
            'parent_face': None,
            'shared_edge_center': None,
            'shared_edge_dir': None,
        }
        visited.add(root_idx)
        queue.append(root_face)

        # Snapshot face centers and normals while still in bmesh
        bm_face_centers = {}
        bm_face_normals = {}
        for f in bm.faces:
            bm_face_centers[f.index] = f.calc_center_median().copy()
            bm_face_normals[f.index] = f.normal.copy()

        while queue:
            current_face = queue.popleft()
            for edge in current_face.edges:
                for linked_face in edge.link_faces:
                    if linked_face.index not in visited:
                        visited.add(linked_face.index)
                        edge_verts = list(edge.verts)
                        mid = (edge_verts[0].co + edge_verts[1].co) / 2.0
                        # Store edge direction vector (local space)
                        edge_dir = (edge_verts[1].co - edge_verts[0].co).normalized()
                        face_data[linked_face.index] = {
                            'parent_face': current_face.index,
                            'shared_edge_center': mid.copy(),
                            'shared_edge_dir': edge_dir.copy(),
                        }
                        queue.append(linked_face)

        mw = obj.matrix_world
        mw3 = mw.to_3x3()

        # World-space face centers
        face_centers_ws = {
            idx: mw @ bm_face_centers[idx]
            for idx in face_data
        }

        # --------------------------------------------------
        # Switch to object mode to create armature
        # --------------------------------------------------
        bpy.ops.object.mode_set(mode='OBJECT')

        # Remove old rig if exists
        old_rig = bpy.data.objects.get("PackagingRig")
        if old_rig:
            bpy.data.objects.remove(old_rig, do_unlink=True)

        arm_data = bpy.data.armatures.new("PackagingArmature")
        arm_obj = bpy.data.objects.new("PackagingRig", arm_data)
        context.collection.objects.link(arm_obj)
        context.view_layer.objects.active = arm_obj
        arm_obj.show_in_front = True

        bpy.ops.object.mode_set(mode='EDIT')

        edit_bones = arm_data.edit_bones
        bone_map = {}  # face_index -> bone name

        for face_idx, data in face_data.items():
            face_normal_local = bm_face_normals[face_idx]
            face_normal_ws = (mw3 @ face_normal_local).normalized()
            face_center_ws = face_centers_ws[face_idx]

            if data['parent_face'] is None:
                # -------------------------------------------------------
                # ROOT BONE
                # Lies flat on the base face.
                # Head = face center, tail extends perpendicular to normal
                # (along one of the face's own edges for a stable direction)
                # -------------------------------------------------------
                bone = edit_bones.new("face_root")

                # Pick a stable in-plane direction from first edge of root face
                root_face_obj = None
                bm_tmp = bmesh.new()
                bm_tmp.from_mesh(obj.data)
                bm_tmp.faces.ensure_lookup_table()
                root_face_obj = bm_tmp.faces[face_idx]
                first_edge_dir_local = (
                    root_face_obj.edges[0].verts[1].co -
                    root_face_obj.edges[0].verts[0].co
                ).normalized()
                bm_tmp.free()

                # Project onto face plane (remove normal component)
                dot = first_edge_dir_local.dot(face_normal_local)
                in_plane_local = (first_edge_dir_local - dot * face_normal_local).normalized()
                in_plane_ws = (mw3 @ in_plane_local).normalized()

                bone.head = face_center_ws
                bone.tail = face_center_ws + in_plane_ws * 0.1
                # Roll so bone Z aligns with face normal (panel thickness direction)
                bone.align_roll(face_normal_ws)
                bone_map[face_idx] = bone.name

            else:
                # -------------------------------------------------------
                # CHILD BONE
                #
                # Goal:
                #   - Head  = shared edge midpoint  (fold pivot)
                #   - Tail  = opposite side of face  (full face span)
                #   - Y axis (head→tail) lies IN the face plane,
                #     perpendicular to the shared edge
                #   - Z axis (roll) aligns with face normal so that
                #     rotating around bone X folds the panel
                # -------------------------------------------------------
                bone = edit_bones.new(f"face_{face_idx}")

                edge_dir_local = data['shared_edge_dir']
                edge_mid_local = data['shared_edge_center']

                # In-face direction perpendicular to the shared edge:
                # cross(face_normal, edge_dir) gives a vector in the face
                # plane that is perpendicular to the edge.
                perp_local = face_normal_local.cross(edge_dir_local)
                if perp_local.length < 1e-6:
                    perp_local = face_normal_local  # fallback
                else:
                    perp_local = perp_local.normalized()

                # Make sure perp points from edge toward face center
                to_center_local = bm_face_centers[face_idx] - edge_mid_local
                if perp_local.dot(to_center_local) < 0:
                    perp_local = -perp_local

                # World-space equivalents
                pivot_ws = mw @ edge_mid_local
                perp_ws = (mw3 @ perp_local).normalized()

                # Full face span: distance from edge midpoint to face center × 2
                half_span = (face_center_ws - pivot_ws).length
                full_span = half_span * 2.0
                if full_span < 0.001:
                    full_span = 0.05

                bone.head = pivot_ws
                bone.tail = pivot_ws + perp_ws * full_span

                # Align roll so bone Z points along face normal.
                # This means a rotation around bone X = fold around the shared edge.
                bone.align_roll(face_normal_ws)

                bone_map[face_idx] = bone.name

        # Assign parents
        for face_idx, data in face_data.items():
            parent_idx = data['parent_face']
            if parent_idx is not None and parent_idx in bone_map:
                edit_bones[bone_map[face_idx]].parent = edit_bones[bone_map[parent_idx]]
                edit_bones[bone_map[face_idx]].use_connect = False

        bpy.ops.object.mode_set(mode='OBJECT')

        # --------------------------------------------------
        # Vertex groups + armature modifier on mesh
        # --------------------------------------------------
        context.view_layer.objects.active = obj
        obj.vertex_groups.clear()

        bm2 = bmesh.new()
        bm2.from_mesh(obj.data)
        bm2.faces.ensure_lookup_table()

        for face_idx, bone_name in bone_map.items():
            vg = obj.vertex_groups.new(name=bone_name)
            vert_indices = [v.index for v in bm2.faces[face_idx].verts]
            vg.add(vert_indices, 1.0, 'REPLACE')

        bm2.free()

        # Remove existing armature modifier
        for m in [m for m in obj.modifiers if m.type == 'ARMATURE']:
            obj.modifiers.remove(m)

        arm_mod = obj.modifiers.new(name="PackagingRig", type='ARMATURE')
        arm_mod.object = arm_obj
        obj.parent = arm_obj

        # --------------------------------------------------
        # Pose: set XYZ rotation mode + 90° default for all bones
        # --------------------------------------------------
        context.view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode='POSE')

        for pbone in arm_obj.pose.bones:
            pbone.rotation_mode = 'XYZ'
            if pbone.name != "face_root":
                pbone.rotation_euler.x = -math.pi / 2

            # Sadece X ekseninde dönüşe izin ver, Y ve Z kilitli (root hariç)
            if pbone.name != "face_root":
                con = pbone.constraints.new('LIMIT_ROTATION')
                con.name = "X Only"
                con.use_limit_y = True
                con.min_y = 0.0
                con.max_y = 0.0
                con.use_limit_z = True
                con.min_z = 0.0
                con.max_z = 0.0
                con.owner_space = 'LOCAL'

        bpy.ops.object.mode_set(mode='OBJECT')
        context.view_layer.objects.active = obj

        self.report({'INFO'}, f"Rig created: {len(bone_map)} bones (XYZ mode, default 90°)")
        return {'FINISHED'}


# ----------------------
# FOLD / UNFOLD OPERATORS
# ----------------------

class PACKAGING_OT_fold_all(Operator):
    bl_idname = "packaging.fold_all"
    bl_label = "Fold All (90°)"
    bl_description = "Rotate all non-root bones to 90 degrees (folded)"

    def execute(self, context):
        import mathutils
        arm_obj = bpy.data.objects.get("PackagingRig")
        if arm_obj is None:
            self.report({'ERROR'}, "No PackagingRig found")
            return {'CANCELLED'}

        prev = context.view_layer.objects.active
        context.view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode='POSE')

        for pbone in arm_obj.pose.bones:
            if pbone.name == "face_root":
                continue
            pbone.rotation_mode = 'XYZ'
            pbone.rotation_euler = mathutils.Euler((-math.pi / 2, 0.0, 0.0), 'XYZ')

        bpy.ops.object.mode_set(mode='OBJECT')
        context.view_layer.objects.active = prev
        return {'FINISHED'}


class PACKAGING_OT_unfold_all(Operator):
    bl_idname = "packaging.unfold_all"
    bl_label = "Unfold All (Flat)"
    bl_description = "Reset all bones to flat (0°) position"

    def execute(self, context):
        import mathutils
        arm_obj = bpy.data.objects.get("PackagingRig")
        if arm_obj is None:
            self.report({'ERROR'}, "No PackagingRig found")
            return {'CANCELLED'}

        prev = context.view_layer.objects.active
        context.view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode='POSE')

        for pbone in arm_obj.pose.bones:
            pbone.rotation_mode = 'XYZ'
            pbone.rotation_euler = mathutils.Euler((0.0, 0.0, 0.0), 'XYZ')

        bpy.ops.object.mode_set(mode='OBJECT')
        context.view_layer.objects.active = prev
        return {'FINISHED'}


# ----------------------
# PANEL
# ----------------------

class PACKAGING_PT_panel(Panel):
    bl_label = "Packaging Tool"
    bl_idname = "PACKAGING_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Packaging'

    def draw(self, context):
        layout = self.layout
        props = context.scene.packaging_props

        layout.label(text="Images")
        layout.prop(props, "image_path")
        layout.prop(props, "inner_image_path")

        layout.separator()
        layout.label(text="Paper")
        layout.prop(props, "paper_color")
        layout.prop(props, "thickness")
        layout.operator("packaging.create_plane")

        layout.separator()
        layout.label(text="Edit Tools")
        layout.operator("packaging.delete_faces")
        layout.operator("packaging.dissolve_faces")

        layout.separator()
        box = layout.box()
        box.label(text="Auto Rig", icon='ARMATURE_DATA')
        box.label(text="1. Edit Mode → select BASE face", icon='INFO')
        box.label(text="2. Press button below", icon='INFO')
        box.operator("packaging.auto_rig", icon='BONE_DATA')

        layout.separator()
        layout.label(text="Animation")
        row = layout.row(align=True)
        row.operator("packaging.fold_all", icon='TRIA_UP')
        row.operator("packaging.unfold_all", icon='TRIA_DOWN')


# ----------------------
# REGISTER
# ----------------------

classes = (
    PackagingProps,
    PACKAGING_OT_create_plane,
    PACKAGING_OT_delete_faces,
    PACKAGING_OT_dissolve_faces,
    PACKAGING_OT_auto_rig,
    PACKAGING_OT_fold_all,
    PACKAGING_OT_unfold_all,
    PACKAGING_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.packaging_props = bpy.props.PointerProperty(type=PackagingProps)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.packaging_props


if __name__ == "__main__":
    register()
