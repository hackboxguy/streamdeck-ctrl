#!/bin/bash
# Sharp lamps: telltales as a bare stencil instead of a glyph over a halo.
#
# One key drives both switches because they are one look: the halo is the
# blur, and the 12% ghost of an unlit lamp is the other thing that keeps the
# band from reading as pure black. Either alone is a half measure. The flags
# stay independent on the command line for anyone who wants just one.
#
# "on" here means sharp is on, i.e. glow and ghosts off -- the key names the
# effect the operator wants, not the flag that produces it.
set -u
. "$(dirname "$0")/cluster-env.sh"

case "${1:-}" in
    on)   extra="--telltale-glow=off --telltale-min-dark-level=off" ;;
    off)  extra="" ;;
    *)    echo "usage: $(basename "$0") on|off" >&2; exit 2 ;;
esac

args="$(cluster_args_without telltale-glow telltale-min-dark-level)"
write_cluster_args "$args${extra:+ $extra}"
notify cluster.lamps "${1}"
