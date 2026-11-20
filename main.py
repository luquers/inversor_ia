"""
Asistente de inversión: Fórmula Mágica (Greenblatt) + F-Score (Piotroski).

Comandos:
  python main.py ranking                       Mejores empresas hoy
  python main.py crear --nombre prueba         Nueva cartera con dinero ficticio
  python main.py crear --nombre diaria --estilo diaria   Cartera que opera cada día (o --estilo semanal)
  python main.py estado [--nombre prueba]      Cómo va tu cartera simulada
  python main.py actualizar [--nombre prueba]  Avanza la cartera simulada a hoy
  python main.py pasado [--inicio 2012-01-01]  Cómo te habría ido en el pasado
  python main.py diario                        Tarea automática diaria (+ alertas)
  python main.py panel                         Regenera el panel web (docs/index.html)
"""
import argparse
import sys

import pandas as pd
import yaml

from inversor.analisis import enviar_alerta, guardar_ranking, informe_semanal, ranking_actual, tabla_texto
from inversor.datos import RAIZ
from inversor import simulacion as sim
from inversor.web import generar_panel


def cargar_config():
    with open(RAIZ / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def actualizar_panel(cfg):
    if (cfg.get("web") or {}).get("activo", True):
        ruta = generar_panel(cfg)
        print(f"Panel actualizado: {ruta}")


def cmd_ranking(cfg, args):
    ranking = ranking_actual(cfg)
    ruta = guardar_ranking(ranking)
    print(f"\nMejores empresas según la Fórmula Mágica con F-Score ≥ {cfg['fscore_minimo']}:\n")
    print(tabla_texto(ranking, args.top))
    print(f"\nEmpresas analizadas: {len(ranking)}  |  Aptas: {int(ranking['apto'].sum())}")
    print(f"Ranking completo guardado en {ruta}")


def cmd_crear(cfg, args):
    sim.crear_cartera(args.nombre, args.capital, cfg, args.estilo)
    print(f"Cartera «{args.nombre}» ({args.estilo}) creada con {args.capital:,.0f} $ ficticios. "
          "Haciendo las primeras compras...")
    estado, ops = sim.actualizar_cartera(args.nombre, cfg)
    print(sim.describir_cartera(estado, ops))
    actualizar_panel(cfg)


def _nombres(args):
    nombres = [args.nombre] if args.nombre else sim.listar_carteras()
    if not nombres:
        sys.exit("No hay carteras simuladas. Crea una con: python main.py crear --nombre prueba")
    return nombres


def cmd_estado(cfg, args):
    for nombre in _nombres(args):
        estado = sim.cargar(nombre)
        print(sim.describir_cartera(estado))
        ruta = sim.grafico_cartera(estado)
        if ruta:
            print(f"Gráfico: {ruta}")
        print()


def cmd_actualizar(cfg, args):
    ranking = None
    for nombre in _nombres(args):
        if ranking is None and sim.toca_rebalancear(sim.cargar(nombre)):
            ranking = ranking_actual(cfg)
        estado, ops = sim.actualizar_cartera(nombre, cfg, ranking)
        print(sim.describir_cartera(estado, ops) + "\n")
    actualizar_panel(cfg)


def cmd_pasado(cfg, args):
    if args.sin_fscore:
        cfg["fscore_minimo"] = 0
    sim.backtest(cfg, args.inicio, args.fin, args.capital)
    actualizar_panel(cfg)


def cmd_diario(cfg, args):
    hoy = pd.Timestamp.today()
    hay_informe = args.forzar_informe or hoy.weekday() == cfg["alertas"]["dia_informe"]
    carteras = sim.listar_carteras()
    necesita_ranking = hay_informe or any(sim.toca_rebalancear(sim.cargar(n)) for n in carteras)
    ranking = ranking_actual(cfg) if necesita_ranking else None

    mensajes, vigiladas = [], list(cfg["alertas"].get("mis_acciones") or [])
    for nombre in carteras:
        estado, ops = sim.actualizar_cartera(nombre, cfg, ranking)
        vigiladas += list(estado["cartera"]["posiciones"])
        if ops or hay_informe:
            mensajes.append(sim.describir_cartera(estado, ops))
    if hay_informe:
        mensajes.insert(0, informe_semanal(ranking, cfg, vigiladas))
    if mensajes:
        enviar_alerta("\n\n".join(mensajes))
    else:
        print("Hoy no hay novedades.")
    actualizar_panel(cfg)


def cmd_panel(cfg, args):
    actualizar_panel(cfg)


def main():
    p = argparse.ArgumentParser(description="Asistente de inversión: Fórmula Mágica + F-Score")
    sub = p.add_subparsers(dest="comando", required=True)

    s = sub.add_parser("ranking", help="Mejores empresas hoy")
    s.add_argument("--top", type=int, default=30)
    s.set_defaults(func=cmd_ranking)

    s = sub.add_parser("crear", help="Crear cartera con dinero ficticio")
    s.add_argument("--nombre", required=True)
    s.add_argument("--capital", type=float, default=10_000)
    s.add_argument("--estilo", choices=sim.ESTILOS, default="trimestral",
                   help="trimestral: reglas de Greenblatt (por defecto). semanal / diaria: compra y vende "
                        "según el ranking cada semana / cada día")
    s.set_defaults(func=cmd_crear)

    for nombre, func, ayuda in [("estado", cmd_estado, "Ver carteras simuladas"),
                                ("actualizar", cmd_actualizar, "Avanzar carteras simuladas a hoy")]:
        s = sub.add_parser(nombre, help=ayuda)
        s.add_argument("--nombre")
        s.set_defaults(func=func)

    s = sub.add_parser("pasado", help="Simular cómo habría ido en el pasado")
    s.add_argument("--inicio", help="AAAA-MM-DD (si no lo pones, la fecha más antigua con datos suficientes)")
    s.add_argument("--fin", help="AAAA-MM-DD (por defecto, hoy)")
    s.add_argument("--capital", type=float, default=10_000)
    s.add_argument("--sin-fscore", action="store_true", help="Solo Fórmula Mágica, sin el filtro de Piotroski")
    s.set_defaults(func=cmd_pasado)

    s = sub.add_parser("panel", help="Regenera el panel web")
    s.set_defaults(func=cmd_panel)

    s = sub.add_parser("diario", help="Tarea diaria: actualiza carteras y envía alertas")
    s.add_argument("--forzar-informe", action="store_true")
    s.set_defaults(func=cmd_diario)

    args = p.parse_args()
    args.func(cargar_config(), args)


if __name__ == "__main__":
    main()
