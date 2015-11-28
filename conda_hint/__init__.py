#!/usr/bin/env python
"""conda-hint: Hint as to why a given set of conda package specs are
unsatisfiable.

Examples:
$ conda-hint 'numpy 1.9*' 'python 3.5*' scikit-learn
$ conda-hint 'numpy'

"""
import sys
import argparse
from collections import defaultdict, OrderedDict

import conda.config                           # type: ignore
from conda.api import get_index               # type: ignore
from conda.resolve import Resolve, MatchSpec  # type: ignore
from conda.toposort import toposort           # type: ignore
from termcolor import colored                 # type: ignore
from typing import Dict, List, Tuple, Set


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument('specs', nargs='+', help='One or more package specifications. '
    		'Note that to use spaces inside\na spec, you need to enclose it in '
    		'quotes on the command line. \nExamples: \'numpy 1.9*\' scikit-learn \'python 3.5*\'')
    p.add_argument(
        '-p', '--platform',
        choices=['linux-64', 'linux-32', 'osx-64', 'win-32', 'win-64'],
        default=conda.config.subdir,
        help='The platform. Default: \'%s\'' % conda.config.subdir)

    args = p.parse_args()
    print(args)

    conda.config.platform = args.platform.split('-')[0]
    conda.config.subdir = args.platform

    index = get_index()
    resolver = Resolve(index)

    try:
        fns = []
        for fn in resolver.solve(args.specs, minimal_hint=False):
            fns.append(fn)
        print('\n\nFound solution:')
        print(' ', '\n  '.join(fns))
        return 0

    except SystemExit as e:
        print(str(e))

    print("Generating hint: %s" % (', '.join(args.specs)))
    execute(args.specs, resolver)

    return 1


def execute(specs: List[str], r: Resolve) -> None:
    mspecs = [MatchSpec(m) for m in specs]
    depgraph, pkgs = implicated_packages(specs, r)

    # mapping from package name to all of the filenames that are plausible
    # installation candidates for that package
    valid = {}  # type: Dict

    # when all of the plausible installation candidates for a package are
    # removed from ``valid``, we record the reason for that exclusion in
    # this dict, which maps package names to descriptions (english strings).
    exclusion_reasons = OrderedDict()  # type: OrderedDict

    for pkg in pkgs:
        try:
            # if we have a matchspec for this package, get the valid files
            # for it.
            ms = next((ms for ms in mspecs if ms.name == MatchSpec(pkg).name))
        except StopIteration:
            # if this package is an indirect dependency, we just have the name,
            # so we get all of the candidate files
            ms = MatchSpec(pkg)
        valid[pkg] = list(r.find_matches(ms))

    while True:
        # in each iteration of this loop, we try to prune out some packages
        # from the valid dict.

        # first, record the number of filenames in the valid dict. use this
        # to ditect convergence and control terminatio of the while loop.
        pre_length = sum(len(fns) for fns in valid.values())

        for key, fns in valid.items():
            satisfied = {}  # type: Dict[str, dict[MatchSpec, bool]]
            for fn in fns:
                satisfied[fn] = {
                    ms: any(depfn in valid[ms.name]
                            for depfn in r.find_matches(ms))
                    for ms in r.ms_depends(fn)
                }
            valid[key] = {fn for fn, sat in satisfied.items()
                          if all(sat.values())}

            if len(valid[key]) == 0 and key not in exclusion_reasons:
                fn2coloreddeps = {}  # type: Dict[str, str]
                for fn, sat in satisfied.items():
                    parts = [colored(d.spec, 'green' if sat[d] else 'red')
                             for d in sorted(sat, key=lambda m: m.spec)]
                    fn2coloreddeps[fn] = ', '.join(parts)

                lines = ['No %s binary matches specs:' % colored(key, 'blue')]
                for fn in sorted(fn2coloreddeps.keys())[::-1]:
                    coloreddeps = fn2coloreddeps[fn]
                    lines.append(''.join(('  ', fn, ': ', coloreddeps)))
                exclusion_reasons[key] = '\n'.join(lines)

            if len(valid[key]) == 0 and any(key == ms.name for ms in mspecs):
                print_output(exclusion_reasons, depgraph)
                return None

        post_length = sum(len(fns) for fns in valid.values())
        if pre_length == post_length:
            break

        return None


def print_output(reasons: OrderedDict, depgraph: Dict) -> None:
    names_printed = set()  # type: Set[str]

    def print_reason(name: str) -> None:
        if name not in reasons or name in names_printed:
            return

        names_printed.add(name)
        print('\n', reasons[name])
        for m in depgraph[name]:
            print_reason(m)

    eliminated_on = list(reasons.keys())[-1]
    print_reason(eliminated_on)


def implicated_packages(specs: List[str], r: Resolve) -> Tuple[Dict[str, Set[str]], List[str]]:
    """Get a list of all packages implicated as possible direct or indirect
    depdencies of ``specs``.

    Example
    -------
    >>> r = Resolve(index)
    >>> specs = ('python 3.5*', 'numpy 1.9*', 'statsmodels')
    >>> implicated_packages(specs, r)
    ['msvc_runtime', 'python', 'distribute', 'numpy', 'pytz', 'setuptools',
     'six', 'wheel', 'dateutil', 'patsy', 'pip', 'python-dateutil', 'scipy',
     'pandas', 'statsmodels']
    """
    depgraph = defaultdict(lambda: set())  # type: Dict[str, Set[str]]

    def add_package(spec: str) -> None:
        ms = MatchSpec(spec)
        name = ms.name

        if name in depgraph:
            return

        depnames = {d.name for fn in r.find_matches(ms) for d in r.ms_depends(fn)}
        for depname in depnames:
            depgraph[name].add(depname)
            add_package(depname)

    for spec in specs:
        add_package(spec)
    return depgraph, toposort(depgraph)


if __name__ == '__main__':
    sys.exit(main())