"""Carga la topología (islas y chasis) en Firestore.

Uso:
  python -m scripts.seed_topologia --archivo config/topologia_demo.json --operator "Nombre"
  python -m scripts.seed_topologia --desde-legado --operator "Nombre" [--dry-run]

--desde-legado migra las colecciones antiguas ISLAS y EQUIPO_CHASIS a las nuevas
``islas`` y ``chasis``. No borra las antiguas. Es idempotente.
"""

import argparse
import json
from pathlib import Path

from backend.services.topology import apply_topology, load_topology_file, read_legacy_topology

from ._bootstrap import bootstrap


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    origen = parser.add_mutually_exclusive_group(required=True)
    origen.add_argument("--archivo", type=Path, help="JSON con 'islas' y 'chasis'")
    origen.add_argument("--desde-legado", action="store_true", help="Migra ISLAS y EQUIPO_CHASIS")
    parser.add_argument("--operator", required=True, help="Nombre de quien ejecuta la carga")
    parser.add_argument("--dry-run", action="store_true", help="Muestra lo que se cargaría sin escribir")
    args = parser.parse_args()

    state, ctx = bootstrap(args.operator)
    warnings: list[str] = []
    if args.archivo:
        seed = load_topology_file(args.archivo)
    else:
        seed, warnings = read_legacy_topology(state.repo)
    for warning in warnings:
        print(f"ADVERTENCIA: {warning}")
    if args.dry_run:
        print(json.dumps(seed.model_dump(), indent=2, ensure_ascii=False))
        return
    counts = apply_topology(state.repo, state.catalog, seed, args.operator, ctx.operation_id)
    state.repo.save_operation({
        "operation_id": ctx.operation_id, "action": "topologia.seed", "method": "CLI",
        "path": "scripts.seed_topologia", "status_code": 200, "outcome": "ok", "operator": args.operator,
        "details": {**counts, "origen": "legado" if args.desde_legado else str(args.archivo),
                    "advertencias": warnings[:50]},
        "created_at": ctx.started_at,
    })
    print(f"{counts['islas']} isla(s) y {counts['chasis']} chasis cargados. Operación {ctx.operation_id}")


if __name__ == "__main__":
    main()
