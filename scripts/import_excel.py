"""Importa un Excel de inventario a Firestore desde la línea de comandos.

Uso:
  python -m scripts.import_excel inventario.xlsx --operator "Nombre" [--mode merge|replace]
"""

import argparse
import json
from pathlib import Path

from backend.app import parse_inventory_excel

from ._bootstrap import bootstrap


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("archivo", type=Path)
    parser.add_argument("--operator", required=True)
    parser.add_argument("--mode", choices=["merge", "replace"], default="merge")
    parser.add_argument("--yes", action="store_true", help="Confirma el modo replace sin preguntar")
    args = parser.parse_args()

    if args.mode == "replace" and not args.yes:
        answer = input("El modo replace borra las IPs de las hojas importadas. Escriba SI para continuar: ")
        if answer.strip().upper() != "SI":
            raise SystemExit("Cancelado.")

    state, ctx = bootstrap(args.operator)
    blocks, ignored = parse_inventory_excel(args.archivo.read_bytes())
    result = state.repo.import_inventory(blocks, mode=args.mode, filename=args.archivo.name,
                                         operator=args.operator, operation_id=ctx.operation_id,
                                         ignored_sheets=ignored)
    summary = result.to_dict()
    state.repo.save_operation({
        "operation_id": ctx.operation_id, "action": "inventory.import", "method": "CLI",
        "path": "scripts.import_excel", "status_code": 200, "outcome": "ok", "operator": args.operator,
        "details": {k: v for k, v in summary.items() if k != "conflicts"}, "created_at": ctx.started_at,
    })
    print(json.dumps({**summary, "operation_id": ctx.operation_id}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
