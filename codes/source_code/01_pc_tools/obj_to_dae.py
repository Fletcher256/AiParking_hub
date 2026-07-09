#!/usr/bin/env python3
"""Stream an OBJ mesh into a Collada 1.4.1 DAE file.

This converter keeps geometry indices compact by using Collada's indexed
VERTEX/TEXCOORD inputs instead of expanding every face corner into a unique
vertex. It intentionally avoids loading the whole mesh into memory.
"""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.parse import quote
from xml.sax.saxutils import escape


ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


@dataclass
class Material:
    name: str
    kd: tuple[float, float, float] = (0.8, 0.8, 0.8)
    ke: tuple[float, float, float] = (0.0, 0.0, 0.0)
    opacity: float = 1.0
    maps: dict[str, str] = field(default_factory=dict)


@dataclass
class FaceGroup:
    material: str
    triangle_count: int = 0


@dataclass
class ObjStats:
    positions: int = 0
    texcoords: int = 0
    normals: int = 0
    groups: list[FaceGroup] = field(default_factory=list)
    material_names: set[str] = field(default_factory=set)
    mtllibs: list[str] = field(default_factory=list)


def clean_id(value: str, default: str) -> str:
    cleaned = ID_RE.sub("_", value.strip())
    cleaned = cleaned.strip("._-")
    if not cleaned:
        cleaned = default
    if not re.match(r"[A-Za-z_]", cleaned[0]):
        cleaned = f"_{cleaned}"
    return cleaned


def fmt_float(value: str) -> str:
    return ("%g" % float(value))


def parse_map_path(parts: list[str]) -> str | None:
    """Return the texture file from an MTL map line, ignoring common options."""

    if not parts:
        return None
    skip_values = {
        "-blendu": 1,
        "-blendv": 1,
        "-boost": 1,
        "-mm": 2,
        "-o": 3,
        "-s": 3,
        "-t": 3,
        "-texres": 1,
        "-clamp": 1,
        "-bm": 1,
        "-imfchan": 1,
        "-type": 1,
    }
    i = 0
    candidates: list[str] = []
    while i < len(parts):
        token = parts[i]
        if token in skip_values:
            i += skip_values[token] + 1
            continue
        if token.startswith("-"):
            i += 1
            continue
        candidates.append(token)
        i += 1
    if not candidates:
        return None
    return " ".join(candidates)


def parse_mtl(path: Path) -> dict[str, Material]:
    materials: dict[str, Material] = {}
    current: Material | None = None
    if not path.exists():
        return materials

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            key = parts[0]
            values = parts[1:]
            if key == "newmtl" and values:
                name = " ".join(values)
                current = Material(name=name)
                materials[name] = current
            elif current is None:
                continue
            elif key == "Kd" and len(values) >= 3:
                current.kd = tuple(float(v) for v in values[:3])  # type: ignore[assignment]
            elif key == "Ke" and len(values) >= 3:
                current.ke = tuple(float(v) for v in values[:3])  # type: ignore[assignment]
            elif key in {"d", "Tr"} and values:
                opacity = float(values[0])
                current.opacity = 1.0 - opacity if key == "Tr" else opacity
            elif key.startswith("map_"):
                texture = parse_map_path(values)
                if texture:
                    current.maps[key] = texture
            elif key in {"bump", "map_Bump"}:
                texture = parse_map_path(values)
                if texture:
                    current.maps["map_Bump"] = texture
    return materials


def face_triangle_count(face_terms: list[str]) -> int:
    return max(0, len(face_terms) - 2)


def scan_obj(path: Path) -> ObjStats:
    stats = ObjStats()
    current_material = "default"
    current_group: FaceGroup | None = None

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("v "):
                stats.positions += 1
            elif line.startswith("vt "):
                stats.texcoords += 1
            elif line.startswith("vn "):
                stats.normals += 1
            elif line.startswith("mtllib "):
                mtllib = line.split(maxsplit=1)[1].strip()
                stats.mtllibs.append(mtllib)
            elif line.startswith("usemtl "):
                current_material = line.split(maxsplit=1)[1].strip() or "default"
                stats.material_names.add(current_material)
                current_group = None
            elif line.startswith("f "):
                triangles = face_triangle_count(line.split()[1:])
                if triangles == 0:
                    continue
                if current_group is None or current_group.material != current_material:
                    current_group = FaceGroup(material=current_material)
                    stats.groups.append(current_group)
                current_group.triangle_count += triangles
                stats.material_names.add(current_material)

    if not stats.material_names:
        stats.material_names.add("default")
    return stats


def obj_index(value: str, count: int) -> int:
    parsed = int(value)
    if parsed < 0:
        return count + parsed
    return parsed - 1


def parse_face_term(term: str, stats: ObjStats) -> tuple[int, int | None, int | None]:
    fields = term.split("/")
    vertex = obj_index(fields[0], stats.positions)
    texcoord = obj_index(fields[1], stats.texcoords) if len(fields) > 1 and fields[1] else None
    normal = obj_index(fields[2], stats.normals) if len(fields) > 2 and fields[2] else None
    return vertex, texcoord, normal


def write_float_array(
    out,
    obj_path: Path,
    prefix: str,
    array_id: str,
    count: int,
    stride: int,
    param_names: Iterable[str],
) -> None:
    out.write(f'      <source id="{array_id}">\n')
    out.write(f'        <float_array id="{array_id}-array" count="{count * stride}">')

    first = True
    with obj_path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            if not raw_line.startswith(prefix):
                continue
            values = raw_line.split()[1 : 1 + stride]
            if len(values) < stride:
                continue
            if not first:
                out.write(" ")
            out.write(" ".join(fmt_float(value) for value in values))
            first = False

    out.write("</float_array>\n")
    out.write("        <technique_common>\n")
    out.write(f'          <accessor source="#{array_id}-array" count="{count}" stride="{stride}">\n')
    for param in param_names:
        out.write(f'            <param name="{param}" type="float"/>\n')
    out.write("          </accessor>\n")
    out.write("        </technique_common>\n")
    out.write("      </source>\n")


def write_p_indices(out, triangles: list[tuple[tuple[int, int | None, int | None], ...]], has_uv: bool) -> None:
    first = True
    for triangle in triangles:
        for vertex, texcoord, _normal in triangle:
            values = [vertex]
            if has_uv:
                values.append(0 if texcoord is None else texcoord)
            if not first:
                out.write(" ")
            out.write(" ".join(str(value) for value in values))
            first = False


def iter_triangles(face_terms: list[str], stats: ObjStats):
    corners = [parse_face_term(term, stats) for term in face_terms]
    for index in range(1, len(corners) - 1):
        yield (corners[0], corners[index], corners[index + 1])


def texture_uri(path: str) -> str:
    return quote(path.replace("\\", "/"))


def write_library_images(out, materials: dict[str, Material]) -> dict[tuple[str, str], str]:
    image_ids: dict[tuple[str, str], str] = {}
    out.write("  <library_images>\n")
    emitted: set[str] = set()
    for material in materials.values():
        material_id = clean_id(material.name, "material")
        for map_key, texture in material.maps.items():
            image_id = clean_id(f"{material_id}_{map_key}_image", "image")
            if image_id in emitted:
                continue
            emitted.add(image_id)
            image_ids[(material.name, map_key)] = image_id
            out.write(f'    <image id="{image_id}" name="{escape(Path(texture).name)}">\n')
            out.write(f"      <init_from>{escape(texture_uri(texture))}</init_from>\n")
            out.write("    </image>\n")
    out.write("  </library_images>\n")
    return image_ids


def write_effects(out, materials: dict[str, Material], image_ids: dict[tuple[str, str], str]) -> None:
    out.write("  <library_effects>\n")
    for material in materials.values():
        material_id = clean_id(material.name, "material")
        effect_id = f"{material_id}-effect"
        diffuse_image = image_ids.get((material.name, "map_Kd"))
        out.write(f'    <effect id="{effect_id}" name="{escape(material.name)}">\n')
        out.write("      <profile_COMMON>\n")
        if diffuse_image:
            surface_sid = f"{material_id}_diffuse_surface"
            sampler_sid = f"{material_id}_diffuse_sampler"
            out.write(f'        <newparam sid="{surface_sid}">\n')
            out.write("          <surface type=\"2D\">\n")
            out.write(f"            <init_from>{diffuse_image}</init_from>\n")
            out.write("          </surface>\n")
            out.write("        </newparam>\n")
            out.write(f'        <newparam sid="{sampler_sid}">\n')
            out.write("          <sampler2D>\n")
            out.write(f"            <source>{surface_sid}</source>\n")
            out.write("          </sampler2D>\n")
            out.write("        </newparam>\n")
        out.write('        <technique sid="common">\n')
        out.write("          <phong>\n")
        out.write(f"            <emission><color>{material.ke[0]:g} {material.ke[1]:g} {material.ke[2]:g} 1</color></emission>\n")
        if diffuse_image:
            out.write(f'            <diffuse><texture texture="{material_id}_diffuse_sampler" texcoord="UVSET0"/></diffuse>\n')
        else:
            out.write(f"            <diffuse><color>{material.kd[0]:g} {material.kd[1]:g} {material.kd[2]:g} 1</color></diffuse>\n")
        if material.opacity < 1.0:
            out.write(f"            <transparent opaque=\"A_ONE\"><color>1 1 1 {material.opacity:g}</color></transparent>\n")
            out.write(f"            <transparency><float>{material.opacity:g}</float></transparency>\n")
        out.write("          </phong>\n")
        out.write("        </technique>\n")
        out.write("      </profile_COMMON>\n")
        extra_maps = {key: value for key, value in material.maps.items() if key != "map_Kd"}
        if extra_maps:
            out.write("      <extra>\n")
            out.write('        <technique profile="OBJ_MTL_PBR_MAPS">\n')
            for key, value in sorted(extra_maps.items()):
                out.write(f"          <{escape(key)}>{escape(texture_uri(value))}</{escape(key)}>\n")
            out.write("        </technique>\n")
            out.write("      </extra>\n")
        out.write("    </effect>\n")
    out.write("  </library_effects>\n")


def write_materials(out, materials: dict[str, Material]) -> None:
    out.write("  <library_materials>\n")
    for material in materials.values():
        material_id = clean_id(material.name, "material")
        out.write(f'    <material id="{material_id}" name="{escape(material.name)}">\n')
        out.write(f'      <instance_effect url="#{material_id}-effect"/>\n')
        out.write("    </material>\n")
    out.write("  </library_materials>\n")


def write_triangles(out, obj_path: Path, stats: ObjStats, material_ids: dict[str, str]) -> None:
    has_uv = stats.texcoords > 0
    group_iter = iter(stats.groups)
    current_group = next(group_iter, None)
    current_material = "default"
    p_open = False

    def close_group() -> None:
        nonlocal p_open
        if p_open:
            out.write("</p>\n")
            out.write("      </triangles>\n")
            p_open = False

    def open_group(group: FaceGroup) -> None:
        nonlocal p_open
        material_id = material_ids.get(group.material, material_ids["default"])
        out.write(f'      <triangles material="{material_id}" count="{group.triangle_count}">\n')
        out.write('        <input semantic="VERTEX" source="#mesh-vertices" offset="0"/>\n')
        if has_uv:
            out.write('        <input semantic="TEXCOORD" source="#mesh-map-0" offset="1" set="0"/>\n')
        out.write("        <p>")
        p_open = True

    first_index_in_group = True
    with obj_path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("usemtl "):
                current_material = line.split(maxsplit=1)[1].strip() or "default"
            elif line.startswith("f "):
                face_terms = line.split()[1:]
                triangles = list(iter_triangles(face_terms, stats))
                if not triangles:
                    continue
                if current_group is None:
                    raise RuntimeError("OBJ face group scan mismatch")
                if not p_open:
                    open_group(current_group)
                    first_index_in_group = True
                if current_group.material != current_material:
                    close_group()
                    current_group = next(group_iter, None)
                    if current_group is None or current_group.material != current_material:
                        raise RuntimeError("OBJ material group scan mismatch")
                    open_group(current_group)
                    first_index_in_group = True

                for triangle in triangles:
                    for vertex, texcoord, _normal in triangle:
                        values = [vertex]
                        if has_uv:
                            values.append(0 if texcoord is None else texcoord)
                        if not first_index_in_group:
                            out.write(" ")
                        out.write(" ".join(str(value) for value in values))
                        first_index_in_group = False

    close_group()


def convert_obj_to_dae(obj_path: Path, dae_path: Path) -> ObjStats:
    stats = scan_obj(obj_path)
    if stats.positions == 0:
        raise ValueError(f"No positions found in {obj_path}")

    materials: dict[str, Material] = {}
    for mtllib in stats.mtllibs:
        materials.update(parse_mtl(obj_path.parent / mtllib))
    for name in sorted(stats.material_names):
        materials.setdefault(name, Material(name=name))
    materials.setdefault("default", Material(name="default"))
    material_ids = {name: clean_id(name, "material") for name in materials}

    dae_path.parent.mkdir(parents=True, exist_ok=True)
    with dae_path.open("w", encoding="utf-8", newline="\n") as out:
        out.write('<?xml version="1.0" encoding="utf-8"?>\n')
        out.write('<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1">\n')
        out.write("  <asset>\n")
        out.write("    <contributor><authoring_tool>tools/obj_to_dae.py</authoring_tool></contributor>\n")
        out.write('    <unit name="meter" meter="1"/>\n')
        out.write("    <up_axis>Y_UP</up_axis>\n")
        out.write("  </asset>\n")

        image_ids = write_library_images(out, materials)
        write_effects(out, materials, image_ids)
        write_materials(out, materials)

        out.write("  <library_geometries>\n")
        out.write('    <geometry id="mesh" name="mesh">\n')
        out.write("      <mesh>\n")
        write_float_array(out, obj_path, "v ", "mesh-positions", stats.positions, 3, ("X", "Y", "Z"))
        if stats.texcoords:
            write_float_array(out, obj_path, "vt ", "mesh-map-0", stats.texcoords, 2, ("S", "T"))
        out.write('      <vertices id="mesh-vertices">\n')
        out.write('        <input semantic="POSITION" source="#mesh-positions"/>\n')
        out.write("      </vertices>\n")
        write_triangles(out, obj_path, stats, material_ids)
        out.write("      </mesh>\n")
        out.write("    </geometry>\n")
        out.write("  </library_geometries>\n")

        out.write("  <library_visual_scenes>\n")
        out.write('    <visual_scene id="Scene" name="Scene">\n')
        out.write('      <node id="mesh-node" name="mesh">\n')
        out.write('        <instance_geometry url="#mesh">\n')
        out.write("          <bind_material>\n")
        out.write("            <technique_common>\n")
        for name, material_id in sorted(material_ids.items()):
            out.write(f'              <instance_material symbol="{material_id}" target="#{material_id}">\n')
            out.write("                <bind_vertex_input semantic=\"UVSET0\" input_semantic=\"TEXCOORD\" input_set=\"0\"/>\n")
            out.write("              </instance_material>\n")
        out.write("            </technique_common>\n")
        out.write("          </bind_material>\n")
        out.write("        </instance_geometry>\n")
        out.write("      </node>\n")
        out.write("    </visual_scene>\n")
        out.write("  </library_visual_scenes>\n")
        out.write("  <scene><instance_visual_scene url=\"#Scene\"/></scene>\n")
        out.write("</COLLADA>\n")

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert an OBJ mesh to Collada DAE.")
    parser.add_argument("obj", type=Path, help="Input OBJ file")
    parser.add_argument("dae", type=Path, nargs="?", help="Output DAE file")
    args = parser.parse_args()

    obj_path = args.obj.resolve()
    dae_path = args.dae.resolve() if args.dae else obj_path.with_suffix(".dae")
    stats = convert_obj_to_dae(obj_path, dae_path)
    triangle_count = sum(group.triangle_count for group in stats.groups)
    print(f"Wrote {dae_path}")
    print(f"positions={stats.positions} texcoords={stats.texcoords} triangles={triangle_count} groups={len(stats.groups)}")


if __name__ == "__main__":
    main()
