#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Resolve the USB clock/reset/PHY/supply graph in original and candidate DTs."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import struct

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PACKAGE = ROOT / 'outputs/rk3568-boot-package-20261005'
ORIGINAL = PACKAGE / 'build/roundtrip-v1/rsce/arch/arm64/boot/dts/rockchip/rk3568_smdt_3568a_v20.dtb'
ORIGINAL_SHA = '83aa4a285dbc8bff3ae3a72a14e371faa54e7598808c4c6ace2834aeb9c9f956'
CANDIDATE_SHA = 'cb3028a4dab33596532557ef59ea8fc99d1517c2474f2816900238ce53cdd279'
ARRAYS = {'clocks': '#clock-cells', 'assigned-clocks': '#clock-cells',
          'assigned-clock-parents': '#clock-cells', 'resets': '#reset-cells',
          'phys': '#phy-cells', 'power-domains': '#power-domain-cells',
          'gpios': '#gpio-cells', 'gpio': '#gpio-cells'}
SINGLE = {'rockchip,usbgrf', 'rockchip,usbctrl-grf', 'rockchip,grf', 'rockchip,pmugrf',
          'rockchip,pipe-grf', 'rockchip,pipe-phy-grf', 'interrupt-parent', 'extcon'}
LISTS = {'pm_qos'}
STRINGS = {'compatible', 'status', 'clock-names', 'reset-names', 'phy-names',
           'regulator-name', 'clock-output-names', 'dr_mode', 'phy_type', 'pinctrl-names'}
SEEDS = ['/usbdrd', '/usbdrd/dwc3@fcc00000', '/usbhost', '/usbhost/dwc3@fd000000',
         '/usb@fd800000', '/usb@fd840000', '/usb@fd880000', '/usb@fd8c0000']


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def load_semantic():
    path = PACKAGE / 'dt-semantics-v2.py'
    require(sha(path.read_bytes()) == 'b89b3e4dab11281e02ec4a31104907e8b66579ba2e44556c4108d470f468aa56',
            'Semantic parser changed')
    spec = importlib.util.spec_from_file_location('formal_usb_semantic', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cells(value):
    data = bytes.fromhex(value)
    require(len(data) % 4 == 0, 'Phandle property is not cell aligned')
    return list(struct.unpack('>' + 'I' * (len(data) // 4), data))


def string(value):
    data = bytes.fromhex(value)
    require(data.endswith(b'\0'), 'String must end in NUL')
    return data[:-1].decode('ascii').split('\0')


def closure(blob):
    semantic = load_semantic()
    tree = semantic.parse(blob)
    handles = semantic.phandles(tree)
    by_node = {node: {} for node in tree['nodes']}
    for key, value in tree['properties'].items():
        node, name = key.rsplit(':', 1)
        by_node[node][name] = value

    def status(node):
        value = by_node[node].get('status')
        return string(value)[0] if value is not None else '<absent:available>'

    def edges(node):
        found = []
        for prop, value in by_node[node].items():
            count_key = ARRAYS.get(prop)
            if prop.endswith('-gpios'):
                count_key = '#gpio-cells'
            if count_key:
                values, offset = cells(value), 0
                while offset < len(values):
                    handle = values[offset]
                    offset += 1
                    if handle == 0 and prop == 'assigned-clock-parents':
                        found.append({'property': prop, 'provider': None, 'args': [], 'unused_parent': True})
                        continue
                    require(handle in handles, node + ':' + prop + ' unresolved phandle')
                    provider = handles[handle]
                    counts = cells(by_node[provider][count_key])
                    require(len(counts) == 1 and counts[0] <= 8, 'Invalid provider cell count')
                    count = counts[0]
                    require(offset + count <= len(values), 'Truncated phandle arguments')
                    arguments = values[offset:offset + count]
                    found.append({'property': prop, 'provider': provider, 'args': arguments})
                    if prop == 'power-domains' and string(by_node[provider]['compatible']) == ['rockchip,rk3568-power-controller']:
                        require(len(arguments) == 1, 'RK3568 power-domain id')
                        domains = [path for path, attributes in by_node.items()
                                   if path.startswith(provider + '/') and 'reg' in attributes
                                   and cells(attributes['reg']) == arguments]
                        require(len(domains) == 1, 'Unique described power-domain child required')
                        found.append({'property': '<power-domain-description>', 'provider': domains[0], 'args': arguments})
                    offset += count
            elif prop.endswith('-supply') or prop in SINGLE or prop in LISTS or re.fullmatch(r'pinctrl-[0-9]+', prop):
                values = cells(value)
                require(len(values) == 1 or prop in LISTS or prop.startswith('pinctrl-'), 'Expected single provider reference')
                for handle in values:
                    require(handle in handles, node + ':' + prop + ' unresolved phandle')
                    found.append({'property': prop, 'provider': handles[handle], 'args': []})
        if node != '/':
            parent = node.rsplit('/', 1)[0] or '/'
            found.append({'property': '<parent>', 'provider': parent, 'args': []})
        return found

    visited, todo, output = set(), list(SEEDS), {}
    while todo:
        node = todo.pop(0)
        if node in visited:
            continue
        require(node in by_node and len(visited) < 256, 'USB closure node/boundary')
        visited.add(node)
        dependencies = edges(node)
        props = {name: string(value) if name in STRINGS else value
                 for name, value in by_node[node].items() if name not in {'phandle', 'linux,phandle'}}
        ancestors = []
        current = node
        while current != '/':
            current = current.rsplit('/', 1)[0] or '/'
            ancestors.append(current)
        effective = status(node) in {'okay', 'ok', '<absent:available>'} and all(
            status(parent) in {'okay', 'ok', '<absent:available>'} for parent in ancestors)
        output[node] = {'status': status(node), 'effective_available_by_status': effective,
                        'properties': props, 'dependencies': dependencies}
        todo.extend(edge['provider'] for edge in dependencies if edge['provider'] is not None)
    return {'nodes': output, 'node_count': len(output),
            'all_references_in_closed_graph_resolved': True,
            'availability_is_only_dt_status_not_driver_probe_success': True}


def normalized_node(node):
    properties = {name: value for name, value in node['properties'].items()
                  if name not in ARRAYS and name not in SINGLE and name not in LISTS and not name.endswith('-supply')
                  and not name.endswith('-gpios') and not re.fullmatch(r'pinctrl-[0-9]+', name)}
    return {'properties': properties, 'dependencies': node['dependencies']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    out = Path(args.out).absolute()
    require(out == out.resolve() and out.is_relative_to(HERE / 'build'), 'Own fresh ordinary output required')
    candidate = Path(args.candidate)
    original_blob, candidate_blob = ORIGINAL.read_bytes(), candidate.read_bytes()
    require(sha(original_blob) == ORIGINAL_SHA and sha(candidate_blob) == CANDIDATE_SHA, 'DT identity changed')
    graphs = {'original': closure(original_blob), 'candidate': closure(candidate_blob)}
    out.mkdir(parents=True, exist_ok=False)
    for name, graph in graphs.items():
        (out / (name + '-usb-closure.json')).write_text(json.dumps(graph, indent=2) + '\n')
    left, right = graphs['original']['nodes'], graphs['candidate']['nodes']
    common = sorted(left.keys() & right.keys())
    differences = {node: {'original': normalized_node(left[node]), 'candidate': normalized_node(right[node])}
                   for node in common if normalized_node(left[node]) != normalized_node(right[node])}
    report = {'original_sha256': sha(original_blob), 'candidate_sha256': sha(candidate_blob),
              'original_closed_nodes': len(left), 'candidate_closed_nodes': len(right),
              'common_nodes': len(common), 'original_only': sorted(left.keys() - right.keys()),
              'candidate_only': sorted(right.keys() - left.keys()),
              'complete_normalized_common_node_differences': differences,
              'all_graph_references_resolved': True, 'board_tested': False,
              'usb_electrical_verified': False, 'deployed_uboot_probe_verified': False,
              'script_sha256': sha(Path(__file__).read_bytes())}
    (out / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('original_closed_nodes', 'candidate_closed_nodes', 'common_nodes',
                                                  'original_only', 'candidate_only')}))


if __name__ == '__main__':
    main()
