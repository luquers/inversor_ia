"""
Asistente de inversión: Fórmula Mágica (Greenblatt) + F-Score (Piotroski).

Comandos:
  python main.py ranking                       Mejores empresas hoy
  python main.py crear --nombre prueba         Nueva cartera con dinero ficticio
  python main.py crear --nombre diaria --estilo diaria   Cartera que opera cada día (o --estilo semanal)
  python main.py estado [--nombre prueba]      Cómo va tu cartera simulada
  python main.py actualizar [--nombre prueba]  Avanza la cartera simulada a hoy
  python main.py pasado [--inicio 2012-01-01]  Cómo te habría ido en el pasado
  python main.py diario                        Tarea automática diaria (+ parte diario y alertas)
  python main.py vigilar                       Vigilancia durante la sesión (cartera reactiva)
  python main.py panel                         Regenera el panel web (docs/index.html)
"""
import argparse
import sys

import yaml

from inversor.analisis import (avisos_vigilancia, cambios_top, cargar_historial_temas, enviar_alerta,
                               guardar_contexto, guardar_ranking,
                               marcar_informe_enviado, marcar_parte_enviado, parte_ya_enviado, ranking_actual,
                               tabla_texto, toca_informe_semanal)
from inversor import mensajes, mercado
from inversor.datos import RAIZ
from inversor import simulacion as sim
from inversor.web import _ranking_guardado, generar_panel


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


def _nombres_empresas(ranking, tickers):
    """{ticker: nombre} para buscar noticias (si no hay ranking de hoy, el último guardado)."""
    if ranking is None:
        ranking, _ = _ranking_guardado()
    nombres = ranking["nombre"].to_dict() if ranking is not None and "nombre" in ranking else {}
    return {t: nombres.get(t) if isinstance(nombres.get(t), str) else t for t in tickers}


def _contexto(cfg, ranking, tickers, macro):
    """Precios, tendencia y noticias. Si algo falla se sigue sin ello (la reactiva pierde sus filtros)."""
    try:
        fuente = ranking if ranking is not None else _ranking_guardado()[0]
        subsectores = fuente["subsector"].dropna().to_dict() if fuente is not None and "subsector" in fuente else {}
        return mercado.contexto(tickers, cfg["referencia"], _nombres_empresas(ranking, tickers),
                                con_noticias=True, macro=macro, subsectores=subsectores,
                                historial_temas=cargar_historial_temas())
    except Exception as e:
        print(f"No se pudo preparar el contexto de mercado: {e}")
        return None


def cmd_diario(cfg, args):
    toca_informe = toca_informe_semanal(cfg["alertas"]["dia_informe"])
    hay_informe = args.forzar_informe or toca_informe
    carteras = sim.listar_carteras()
    estados = [sim.cargar(n) for n in carteras]
    necesita_ranking = hay_informe or any(sim.toca_rebalancear(e) for e in estados)
    ranking = ranking_actual(cfg) if necesita_ranking else None

    # Contexto: empresas que se tienen + las 30 mejores (posibles compras de la reactiva)
    tenidas = {t for e in estados for t in e["cartera"]["posiciones"]}
    mejores = ranking[ranking["apto"]].head(40).index.tolist() if ranking is not None else []
    ctx = _contexto(cfg, ranking, tenidas | set(mejores), macro=True)

    resultados, vigiladas = [], list(cfg["alertas"].get("mis_acciones") or [])
    for nombre in carteras:
        estado, ops = sim.actualizar_cartera(nombre, cfg, ranking, ctx)
        resultados.append((estado, ops))
        vigiladas += list(estado["cartera"]["posiciones"])
        print(sim.describir_cartera(estado, ops) + "\n")

    info = mensajes.info_empresas(ranking if ranking is not None else _ranking_guardado()[0], extra=vigiladas)
    avisar = []
    fecha_mercado = ctx["fecha_precios"] if ctx else None
    parte = ctx is not None and not parte_ya_enviado(fecha_mercado)
    if parte:
        avisar.append(mensajes.mensaje_parte_diario(resultados, ctx, cfg, info))
    elif any(ops for _, ops in resultados):
        avisar.append(mensajes.mensaje_novedades([(e, o) for e, o in resultados if o], info, cfg))
    else:
        print("Hoy no hay parte: el mercado no ha abierto desde el último (festivo o fin de semana).")
    if hay_informe:
        cambios = cambios_top(ranking, cfg["alertas"]["top_informe"])
        avisos = avisos_vigilancia(ranking, cfg, vigiladas)
        avisar.append(mensajes.mensaje_semanal([e for e, _ in resultados], ranking, cfg, cambios, avisos))
    for texto in avisar:
        enviar_alerta(texto)
    if parte:
        marcar_parte_enviado(fecha_mercado)
    if toca_informe:
        marcar_informe_enviado()
    guardar_contexto(ctx)
    actualizar_panel(cfg)


def cmd_vigilar(cfg, args):
    """Durante la sesión: la cartera reactiva comprueba sus protecciones (stop móvil y noticias graves)."""
    reactivas = [n for n in sim.listar_carteras() if sim.es_reactiva(sim.cargar(n))]
    tenidas = {t for n in reactivas for t in sim.cargar(n)["cartera"]["posiciones"]}
    if not tenidas:
        print("No hay ninguna cartera reactiva con empresas que vigilar.")
        return
    ctx = _contexto(cfg, None, tenidas, macro=False)
    if ctx is None:
        return
    items = []
    for nombre in reactivas:
        ops = sim.vigilar_cartera(nombre, ctx)
        if ops:
            items.append((sim.cargar(nombre), ops))
    if not items:
        print("Vigilancia sin novedades: ninguna protección ha saltado.")
        return
    info = mensajes.info_empresas(_ranking_guardado()[0], extra=tenidas)
    enviar_alerta(mensajes.mensaje_novedades(items, info, cfg))
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

    s = sub.add_parser("vigilar", help="Durante la sesión: protecciones de la cartera reactiva")
    s.set_defaults(func=cmd_vigilar)

    s = sub.add_parser("diario", help="Tarea diaria: actualiza carteras y envía alertas")
    s.add_argument("--forzar-informe", action="store_true")
    s.set_defaults(func=cmd_diario)

    args = p.parse_args()
    args.func(cargar_config(), args)


if __name__ == "__main__":
    main()
