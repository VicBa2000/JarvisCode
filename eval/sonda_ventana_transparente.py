"""Sonda: ¿puede Jarvis ser una capa transparente por encima de todo?

DUDA DEL USUARIO (2026-08-26), planteada como duda y NO como requisito.
Esto no construye nada: abre una ventana de prueba con las tres opciones
puestas para que se pueda VER y decidir con la vista en vez de con una
descripcion.

LO QUE DICE EL CODIGO DE pywebview, que es por donde se empezo:

    # window transparency is supported only with EdgeChromium
        -- webview/platforms/winforms.py

Y en esta maquina el renderer ES `edgechromium` (WebView2 151.0.4129.107,
comprobado el 2026-08-26). O sea que la respuesta corta es SI. Las tres
piezas son independientes:

    transparent=True   no se pinta el fondo de la ventana
    on_top=True        se queda por encima de todo (TopMost)
    frameless=True     sin barra de titulo

>>> LAS DOS TRAMPAS, QUE ES LO QUE NO SE VE EN LA DESCRIPCION <<<

1. **La transparencia la tiene que querer TAMBIEN la pagina.** La
   ventana deja de pintar su fondo, pero si el HTML pinta el suyo opaco
   -- que es lo que hace hoy `consola.html`, la cabina de vidrio y neon
   -- no se transparenta NADA. Por eso esta sonda trae dos paginas: una
   con el fondo a `transparent` y otra opaca, para ver la diferencia con
   los mismos ajustes de ventana.

2. **Una ventana por encima se come los clics de lo que hay debajo.**
   No hay "click-through" aqui: pywebview no expone `WS_EX_TRANSPARENT`.
   O sea que una capa a pantalla completa taparia el escritorio de
   verdad, no solo visualmente. La forma que si funciona es un panel
   PEQUEÑO siempre visible -- una esquina que diga que Jarvis escucha,
   que esta trabajando o que hay una puerta esperando -- y la consola
   entera en su ventana normal.

    .venv\\Scripts\\python.exe -m eval.sonda_ventana_transparente
    .venv\\Scripts\\python.exe -m eval.sonda_ventana_transparente --opaca
"""

from __future__ import annotations

import argparse

PAGINA = """
<html><head><meta charset="utf-8"><style>
  html, body { margin:0; height:100%%; background:%s;
               font-family:Segoe UI, sans-serif; color:#e8f4ff; }
  .caja { position:absolute; inset:18px; border-radius:18px;
          border:1px solid rgba(86,214,255,.55);
          background:rgba(14,18,28,.55);
          backdrop-filter: blur(14px);
          display:flex; flex-direction:column; gap:10px;
          align-items:center; justify-content:center; text-align:center; }
  h1 { margin:0; font-size:20px; letter-spacing:.14em; color:#56d6ff; }
  p  { margin:0; font-size:13px; opacity:.85; max-width:80%%; }
  .punto { width:12px; height:12px; border-radius:50%%; background:#80ffbe;
           box-shadow:0 0 14px #80ffbe; }
</style></head><body>
  <div class="caja">
    <div class="punto"></div>
    <h1>JARVIS</h1>
    <p>%s</p>
    <p style="opacity:.55">Arrastra otra ventana por debajo:
       si se ve a traves de los bordes, la transparencia funciona.</p>
  </div>
</body></html>
"""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--opaca", action="store_true",
                   help="mismo ajuste de ventana, pero con la PAGINA opaca: "
                        "sirve para ver que la transparencia la tienen que "
                        "querer las dos, ventana y HTML")
    p.add_argument("--con-marco", action="store_true",
                   help="deja la barra de titulo")
    p.add_argument("--no-encima", action="store_true",
                   help="sin TopMost, para comparar")
    args = p.parse_args()

    import webview
    import webview.platforms.winforms as wf

    print(f"renderer: {wf.renderer}  (la transparencia SOLO va en edgechromium)")
    if wf.renderer != "edgechromium":
        print(">>> AVISO: sin WebView2 esto no se va a transparentar, y el")
        print(">>> fallo va a ser mudo: la ventana saldra opaca sin dar error.")

    fondo = "#0e121c" if args.opaca else "transparent"
    nota = ("La PAGINA es opaca: la ventana es transparente y aun asi no se ve"
            " nada detras." if args.opaca else
            "Ventana y pagina transparentes. Esto es lo que se veria.")

    webview.create_window(
        "Jarvis (sonda)",
        html=PAGINA % (fondo, nota),
        width=380, height=240,
        transparent=not args.opaca,
        frameless=not args.con_marco,
        on_top=not args.no_encima,
        easy_drag=True,
    )
    webview.start()
    print("cerrada")


if __name__ == "__main__":
    main()
