# Optimization

Both optimizers call the same feasibility and objective evaluator. They do not
maintain independent optical equations.

## Search

Each selected lens is a discrete candidate. Observation angle `α` and image
plane angle `β` are continuous variables with default bounds `15–45°` and
`20–55°`.

Hard constraints include:

- positive object and image distances;
- a nonsingular mapping over the complete measurement interval;
- the complete exact image segment fitting the selected sensor axis;
- available image-circle coverage when known;
- exact conservative `W/R` package limits;
- an image-plane orientation below the configured folded-geometry limit.

Infeasible samples retain normalized violation amounts. They are never shown
as a valid best design.

## Merit

The primary merit is worst-case absolute distance change per pixel over the
measurement interval. Feasible candidates within numerical tolerance are
ordered by:

1. smaller `max(W,R)`;
2. smaller required sensor length;
3. smaller total optical path.

## SciPy product optimizer

The product path uses `scipy.optimize.differential_evolution`, seed 2026,
population `15 × dimensions`, 300 maximum generations, tolerance `1e-8`, and
final polishing. Cancellation is checked through the callback.

## Reproducible M-PSO

The paper leaves some mutation details unspecified, so the application uses
the following explicit interpretation:

- 200 particles, 300 iterations, seed 2026;
- normalized design coordinates;
- inertia decreasing linearly from 0.9 to 0.2;
- cognitive and social coefficients both 2.5;
- normalized velocity clipped to `[-1,4]`;
- Deb ordering: feasible, total violation, objective;
- stagnation after 30 iterations below the normalized improvement threshold;
- if normalized swarm radius is below 0.1 while stagnant, non-best particles
  are independently reset with probability 0.2;
- the global best is retained through mutation.

This mode is labelled a reproducible interpretation, not a bit-identical copy
of unpublished reference code.
