"""Lo que solo puede hacer la CARCASA, en un sitio que ven los dos canales.

>>> POR QUE ESTO EXISTE (2026-09-05) <<<
Lo reporto el usuario probando: dicho por voz, "apagate" lo intercepta
Jarvis y se apaga, que es lo correcto; escrito en la consola, la misma
palabra se le pasaba entera a Claude Code.
Y era exacto: escrito, "apagate" se iba al cerebro, gastaba un turno
entero y Claude Code contestaba una despedida educada mientras Jarvis
seguia vivo.

ES EL MISMO HUECO DEL 2026-09-03 CON OTRA FORMA. Aquel era el cambio de
proyecto, que tambien vivia solo en `voz/bucle.py`. Y el argumento que
justifica interceptar es el mismo y sigue sin depender del canal:

    **se intercepta lo que el cerebro no PUEDE hacer, jamas lo que
    seria mas rapido hacer aqui.**

Claude Code no tiene esta ventana, no sabe que existe y no puede matar el
proceso que lo esta conduciendo. Eso es verdad la digas o la escribas.

>>> POR QUE UN OBJETO Y NO TRES ATRIBUTOS EN CADA SITIO <<<
Los gestos los pone `escritorio/` -- es el unico que tiene pywebview y la
bandeja -- y los necesitan DOS consumidores. Con un juego de atributos
por consumidor, enchufar uno y olvidar el otro da exactamente el fallo
que se esta arreglando: la misma frase haciendo cosas distintas segun el
canal, sin un solo error. Aqui hay UN objeto y se pasa por referencia, asi
que o los tiene los dos o no los tiene ninguno.

>>> Y SE ENCHUFAN AUNQUE NO HAYA VOZ <<<
Hasta hoy `escritorio/__main__.py` los ponia dentro de un
`if voz is not None`, o sea que con `--voz` apagado no habia a quien
pedirle nada -- y ese es justo el modo en el que solo existe la consola.
El segundo fallo estaba debajo del primero.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class Gestos:
    """Enseñar la ventana, esconderla y apagar Jarvis entero.

    Los tres nacen en `None`, y eso NO es "no hace falta": es **no hay
    carcasa**, que es lo que pasa lanzando `-m puente` en una terminal.
    Quien los use tiene que mirar si estan y decirlo, en vez de
    callarse -- callarse se ve igual que no haberte oido.
    """

    mostrar: Callable[[], None] | None = None
    esconder: Callable[[], None] | None = None
    apagar: Callable[[], None] | None = None

    @property
    def hay_carcasa(self) -> bool:
        """Si hay ventana que mover. No dice si se puede APAGAR.

        Son cosas distintas a proposito: `apagar` sale por `_salir`, que
        es la unica puerta que cierra la sesion de Claude Code, y puede
        existir sin que existan las otras dos.
        """
        return self.mostrar is not None or self.esconder is not None
