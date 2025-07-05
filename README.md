# Fold Rig

**Fold Rig** is a Blender add-on for quickly generating bones and vertex groups along a mesh "fold" structure, ideal for rigging folding or chain-like objects.

## Features

- Automatically creates an armature and bones along the selected fold mesh.
- Adds vertex groups for each bone.
- Sets parent-child bone relationships based on mesh connectivity.
- Designed for Blender **4.4.3**.

## Installation

1. Download or clone this repository.
2. In Blender, go to **Edit > Preferences > Add-ons > Install**.
3. Select the `rig.py` file and enable the add-on.

## Usage

1. Prepare two mesh objects:
    - One named **fold** (a mesh representing the fold/chain structure, usually just vertices and edges).
    - One main mesh to be rigged.
2. Select both objects (first the main mesh, then the fold mesh).
3. In the **3D Viewport**, open the **Sidebar** (`N` key), go to the **Fold Rig** tab.
4. Click **Add Bones**.
5. The add-on will create an armature, bones, and vertex groups automatically.

## Notes

- The fold mesh should be a simple edge chain or tree (no cycles).
- The first selected edge in Edit Mode will be used as the root; otherwise, an endpoint is chosen.
- Works with Blender 4.4.3.

