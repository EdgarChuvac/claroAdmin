"""Carga config/centrales.json en la colección 'centrales' de Firestore.

Uso:  python -m scripts.seed_centrales --operator "Nombre Apellido"
"""

import argparse

from backend.services.catalog import load_catalog

from ._bootstrap import bootstrap


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operator", required=True, help="Nombre de quien ejecuta la carga")
    args = parser.parse_args()
    state, ctx = bootstrap(args.operator)
    centrales = [c.model_dump() for c in load_catalog(state.settings.config_dir).centrales]
    count = state.repo.replace_centrales(centrales)
    state.repo.save_operation({
        "operation_id": ctx.operation_id, "action": "centrales.sync", "method": "CLI", "path": "scripts.seed_centrales",
        "status_code": 200, "outcome": "ok", "operator": args.operator, "details": {"count": count},
        "created_at": ctx.started_at,
    })
    print(f"{count} central(es) cargada(s). Operación {ctx.operation_id}")


if __name__ == "__main__":
    main()
