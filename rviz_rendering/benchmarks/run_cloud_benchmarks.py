#!/usr/bin/env python3
# Copyright (c) 2026, John C. Furey
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#    * Redistributions of source code must retain the above copyright
#      notice, this list of conditions and the following disclaimer.
#
#    * Redistributions in binary form must reproduce the above copyright
#      notice, this list of conditions and the following disclaimer in the
#      documentation and/or other materials provided with the distribution.
#
#    * Neither the name of the copyright holder nor the names of its
#      contributors may be used to endorse or promote products derived from
#      this software without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

"""Run serial cloud workloads and preserve raw samples and library identities."""

import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess


WORKLOADS = {
    '1m-points': (1000000, 1, 'points'),
    '6m-points': (6000000, 1, 'points'),
    '250k-boxes': (250000, 1, 'boxes'),
    '100k-decay10': (100000, 10, 'points'),
}


def positive(value):
    result = int(value)
    if result < 1:
        raise argparse.ArgumentTypeError('must be positive')
    return result


def percentile(values, quantile):
    """Nearest-rank quantile, retaining outliers."""
    return sorted(values)[max(0, math.ceil(len(values) * quantile) - 1)]


def library_identities(binary, env):
    result = subprocess.run(['ldd', str(binary)], env=env, check=True,
                            text=True, capture_output=True)
    libraries = {}
    for line in result.stdout.splitlines():
        if '=>' not in line:
            continue
        name, location = line.strip().split(' => ', 1)
        if 'rviz' not in name and 'Ogre' not in name:
            continue
        path = Path(location.rsplit(' (', 1)[0]).resolve()
        libraries[name] = {
            'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    if 'librviz_rendering.so' not in libraries:
        raise RuntimeError('Could not identify the loaded RViz renderer')
    return libraries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--binary', required=True, type=Path)
    parser.add_argument('--baseline-lib-dir', type=Path,
                        help='ABI-compatible pre-change libraries for a paired comparison')
    parser.add_argument('--output', required=True, type=Path,
                        help='new directory for raw logs and results.json')
    parser.add_argument('--samples', type=positive, default=200)
    parser.add_argument('--warmup', type=positive, default=20)
    parser.add_argument('--rounds', type=positive, default=3)
    parser.add_argument('--render', action='store_true',
                        help='also render each update; measures the CPU render call, not GPU time')
    parser.add_argument('--workload', choices=WORKLOADS, action='append')
    args = parser.parse_args()
    binary = args.binary.resolve(strict=True)
    workloads = args.workload or list(WORKLOADS)
    if any(args.warmup < WORKLOADS[name][1] for name in workloads):
        parser.error('warmup must fill the retained batches')
    env = os.environ.copy()
    environments = {'fixed': env}
    if args.baseline_lib_dir:
        baseline = args.baseline_lib_dir.resolve(strict=True)
        if not (baseline / 'librviz_rendering.so').is_file():
            parser.error('baseline directory must contain librviz_rendering.so')
        environments = {'baseline': dict(env), 'fixed': env}
        environments['baseline']['LD_LIBRARY_PATH'] = (
            str(baseline) + ':' + env.get('LD_LIBRARY_PATH', ''))
    identities = {name: library_identities(binary, values)
                  for name, values in environments.items()}
    if 'baseline' in identities and (
        identities['baseline']['librviz_rendering.so']['sha256'] ==
            identities['fixed']['librviz_rendering.so']['sha256']):
        parser.error('baseline and fixed resolve to the same renderer')
    args.output.mkdir(parents=True, exist_ok=False)
    document = {
        'started_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'platform': platform.platform(), 'cpu_count': os.cpu_count(),
        'binary': str(binary), 'libraries': identities,
        'environment': {key: env.get(key) for key in
                        ('QT_QPA_PLATFORM', 'QT_SCALE_FACTOR', 'LIBGL_ALWAYS_SOFTWARE')},
        'parameters': {'samples': args.samples, 'warmup': args.warmup,
                       'rounds': args.rounds, 'render': args.render},
        'runs': [],
    }
    for name in workloads:
        count, batches, mode = WORKLOADS[name]
        for round_index in range(args.rounds):
            order = list(environments)
            if round_index % 2:
                order.reverse()
            for version in order:
                command = [str(binary), str(count), str(args.samples), str(args.warmup),
                           str(batches), mode, 'render' if args.render else 'upload']
                log = args.output / f'{name}-{round_index}-{version}.log'
                with log.open('w') as stream:
                    subprocess.run(command, env=environments[version], stdout=stream,
                                   stderr=subprocess.STDOUT, check=True, timeout=1800)
                samples = []
                metadata = {}
                for line in log.read_text().splitlines():
                    if line.startswith('SAMPLE '):
                        samples.append([float(value) for value in line[7:].split(',')])
                    elif line.startswith(('DEVICE ', 'QT ', 'DRIVER ', 'SCALE ',
                                          'VERTICES_PER_POINT ', 'RETAINED_POINTS ')):
                        key, value = line.split(' ', 1)
                        metadata[key.lower()] = value
                if len(samples) != args.samples:
                    raise RuntimeError(f'Incomplete samples in {log}')
                summary = {}
                for column, label in ((1, 'update_ms'), (2, 'render_call_ms')):
                    values = [sample[column] for sample in samples]
                    summary[label] = {
                        'median': statistics.median(values),
                        'p95': percentile(values, 0.95), 'p99': percentile(values, 0.99),
                        'max': max(values),
                    }
                rss = [sample[3] for sample in samples]
                summary['rss_kib'] = {
                    'first_10_median': statistics.median(rss[:10]),
                    'last_10_median': statistics.median(rss[-10:]), 'max': max(rss)}
                document['runs'].append({
                    'workload': name, 'version': version, 'round': round_index,
                    'command': command, 'metadata': metadata, 'summary': summary,
                    'samples': samples, 'sample_columns':
                    ['index', 'update_ms', 'render_call_ms', 'rss_kib']})
                (args.output / 'results.json').write_text(json.dumps(document, indent=2) + '\n')
                timings = summary['update_ms']
                print(f'{name} {version} round={round_index}: '
                      f'update median={timings["median"]:.3f} '
                      f'p95={timings["p95"]:.3f} p99={timings["p99"]:.3f} ms', flush=True)


if __name__ == '__main__':
    main()
