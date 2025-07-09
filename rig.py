bl_info = {
    "name": "Fold Rig",
    "author": "umtksa",
    "version": (1, 1),
    "blender": (4, 4, 3),
    "location": "View3D > Sidebar > Fold Rig",
    "description": "add bones and vertex groups",
    "category": "Rigging",
}

import bpy
import bmesh
from mathutils import Vector

def build_edge_tree(bm):
    vert_edges = {v.index: [] for v in bm.verts}
    for e in bm.edges:
        vert_edges[e.verts[0].index].append(e)
        vert_edges[e.verts[1].index].append(e)
    return vert_edges

def find_root_vertex(vert_edges):
    for idx, edges in vert_edges.items():
        if len(edges) == 1:
            return idx
    return list(vert_edges.keys())[0]

def traverse_edges(bm, vert_edges, root_idx):
    visited = set()
    stack = [(root_idx, None)]
    edge_order = []
    while stack:
        v_idx, parent = stack.pop()
        if v_idx in visited:
            continue
        visited.add(v_idx)
        for e in vert_edges[v_idx]:
            v1, v2 = e.verts[0].index, e.verts[1].index
            other = v2 if v1 == v_idx else v1
            if other not in visited:
                edge_order.append((e, v_idx, other, parent))
                stack.append((other, v_idx))
    return edge_order

def find_selected_edge_root(bm):
    selected_edges = [e for e in bm.edges if e.select]
    if selected_edges:
        return selected_edges[0].verts[0].index
    return None

class FOLD_OT_add_bones(bpy.types.Operator):
    bl_idname = "foldrig.add_bones"
    bl_label = "Add Bones"
    bl_description = "Add bones and vertex groups starting from the selected edge in the fold object"

    def execute(self, context):
        sel = context.selected_objects
        if len(sel) != 2:
            self.report({'ERROR'}, "Two objects must be selected: fold (vertex mesh) and main mesh.")
            return {'CANCELLED'}

        fold_obj = next((o for o in sel if o.name == "fold"), None)
        mesh_obj = next((o for o in sel if o != fold_obj), None)
        if not fold_obj or not mesh_obj or mesh_obj.type != 'MESH' or fold_obj.type != 'MESH':
            self.report({'ERROR'}, "You must select a vertex mesh named 'fold' and a main mesh.")
            return {'CANCELLED'}

        bm = bmesh.new()
        bm.from_mesh(fold_obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()

        root_idx = find_selected_edge_root(bm)
        if root_idx is None:
            root_idx = find_root_vertex(build_edge_tree(bm))

        vert_edges = build_edge_tree(bm)
        edge_order = traverse_edges(bm, vert_edges, root_idx)

        arm_data = bpy.data.armatures.new(mesh_obj.name + "_RigData")
        arm_obj = bpy.data.objects.new(mesh_obj.name + "_Rig", arm_data)
        context.collection.objects.link(arm_obj)
        arm_obj.show_in_front = True

        context.view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode='EDIT')
        edit_bones = arm_obj.data.edit_bones

        bone_names = []
        for idx, (e, v_from, v_to, parent_idx) in enumerate(edge_order):
            v1 = bm.verts[v_from]
            v2 = bm.verts[v_to]
            co1 = fold_obj.matrix_world @ v1.co
            co2 = fold_obj.matrix_world @ v2.co
            bone_name = f"bone{idx+1:02d}"
            bone = edit_bones.new(bone_name)
            bone.head = co1
            bone.tail = co2
            if parent_idx is not None:
                try:
                    parent_idx_in_order = next(
                        i for i, (_, f, t, _) in enumerate(edge_order) if (f == parent_idx and t == v_from) or (f == v_from and t == parent_idx)
                    )
                    parent_bone_name = f"bone{parent_idx_in_order+1:02d}"
                    if parent_bone_name in edit_bones:
                        bone.parent = edit_bones[parent_bone_name]
                except StopIteration:
                    pass
            bone_names.append(bone.name)

        bpy.ops.object.mode_set(mode='OBJECT')

        mod = mesh_obj.modifiers.new(name="Armature", type='ARMATURE')
        mod.object = arm_obj
        mesh_obj.parent = arm_obj

        for bone_name in bone_names:
            if bone_name not in mesh_obj.vertex_groups:
                mesh_obj.vertex_groups.new(name=bone_name)

        self.report({'INFO'}, "Add Bones: Done")
        return {'FINISHED'}

class FOLD_OT_delete_bones_preserve_hierarchy(bpy.types.Operator):
    bl_idname = "foldrig.delete_bones_preserve"
    bl_label = "Delete Bones"
    bl_description = "Delete selected bones and preserve parent-child hierarchy and clean weights"

    def execute(self, context):
        obj = context.object
        if not obj or obj.type != 'ARMATURE':
            self.report({'ERROR'}, "Select an Armature object.")
            return {'CANCELLED'}

        bpy.ops.object.mode_set(mode='EDIT')
        edit_bones = obj.data.edit_bones
        selected_bones = [b for b in edit_bones if b.select]

        deleted_bone_names = []

        for bone in selected_bones:
            parent = bone.parent
            children = [b for b in edit_bones if b.parent == bone]
            for child in children:
                child.parent = parent
                if parent:
                    child.use_connect = False
            deleted_bone_names.append(bone.name)
            edit_bones.remove(bone)

        bpy.ops.object.mode_set(mode='OBJECT')

        # Silinen kemik isimleriyle eşleşen vertex group'ları sil
        for child_obj in context.scene.objects:
            if child_obj.parent == obj and child_obj.type == 'MESH':
                for bone_name in deleted_bone_names:
                    vg = child_obj.vertex_groups.get(bone_name)
                    if vg:
                        child_obj.vertex_groups.remove(vg)

        self.report({'INFO'}, "Delete Bones: Done (bones + vertex groups removed)")
        return {'FINISHED'}


class FOLD_PT_panel(bpy.types.Panel):
    bl_label = "Fold Rig"
    bl_idname = "FOLD_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Fold Rig"

    def draw(self, context):
        layout = self.layout
        layout.operator("foldrig.add_bones", icon='BONE_DATA')
        layout.operator("foldrig.delete_bones_preserve", icon='X')

classes = [FOLD_OT_add_bones, FOLD_OT_delete_bones_preserve_hierarchy, FOLD_PT_panel]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
