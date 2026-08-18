#!/usr/bin/env python3
"""Registro de promessas do agente.

Toda frase que descreve trabalho futuro entra numa tabela ANTES de a mensagem
sair pro Telegram, não depois. Motivo: promessa descrita e nunca despachada,
descoberta pelo Chefe sozinho, é o pior jeito de perder confiança — e agente
que só lê arquivo (não banco) não tem como saber que algo mudou se a entrega
não deixa rastro em arquivo nenhum.

Este arquivo resolve os dois lados:

  - a promessa entra numa TABELA no momento em que se promete, não depois;
  - o sweep escreve `memory/promessas.md`, que é um arquivo que o agente de
    projetos CONSEGUE ler, com a verdade do banco dentro.

Uso:

    promessas.py add "texto" --prazo 2h --dono paulo-dev --evidencia "rota /pessoa/[id]"
    promessas.py despachar <id> --agent-id abc123
    promessas.py entregar <id> --nota "no ar, conferido logado"
    promessas.py cancelar <id> --nota "o Chefe mudou de ideia"
    promessas.py lista
    promessas.py sweep          # cron: cobra o que venceu e reescreve o .md
"""

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import psycopg2

RAIZ = "/opt/{{AGENTE_NAME_LOWERCASE}}"
ARQUIVO_PROJETOS = f"{RAIZ}/memory/promessas.md"
INJECT = f"{RAIZ}/tools/inject.sh"
BRT = timezone(timedelta(hours=-3))


def conectar():
    """Escrita exige DATABASE_URL. Subagente não chega aqui: ele usa a
    credencial só-leitura e o Postgres recusa o INSERT, que é a trava boa."""
    url = None
    with open(f"{RAIZ}/.env") as f:
        for linha in f:
            if linha.startswith("DATABASE_URL="):
                url = linha.split("=", 1)[1].strip()
    if not url:
        sys.exit("DATABASE_URL não está no .env")
    return psycopg2.connect(url)


def prazo_para_data(texto):
    """Aceita '2h', '30m', '3d' ou uma data ISO. Sem prazo o item nunca vence,
    e item que nunca vence é fácil de perder de vista."""
    if not texto:
        return None
    m = re.fullmatch(r"(\d+)([hmd])", texto.strip())
    if m:
        n, u = int(m.group(1)), m.group(2)
        delta = {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}[u]
        return datetime.now(timezone.utc) + delta
    return datetime.fromisoformat(texto)


def brt(dt):
    return dt.astimezone(BRT).strftime("%d/%m %H:%M") if dt else "sem prazo"


def cmd_add(a):
    # `--despachada` existe pro caso comum de esquecer o segundo passo: criar
    # a promessa, chamar o subagente no mesmo minuto, e esquecer de rodar
    # `despachar`. Duas linhas de comando pra um único ato viram uma linha
    # esquecida; o ato de já estar chamando o agente agora é um comando só.
    status = "despachada" if getattr(a, "despachada", False) else "aberta"
    with conectar() as conn, conn.cursor() as c:
        c.execute(
            "INSERT INTO promessas (texto, dono, evidencia, prazo, msg_id, status) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (a.texto, a.dono, a.evidencia, prazo_para_data(a.prazo), a.msg_id, status),
        )
        conn.commit()
        print(f"promessa #{c.fetchone()[0]} registrada como {status}, "
              f"vence {brt(prazo_para_data(a.prazo))}")


def cmd_estado(a, status):
    # Fechar como "entregue" exige prova, não intenção: código pronto,
    # "subiu" ou "200" não são prova, só uma tela conferida logada, uma rota
    # respondendo de verdade ou uma linha no banco são.
    if status == "entregue" and not a.nota:
        sys.exit(
            "entregar exige --nota com a PROVA, não com a intenção.\n"
            "Vale: tela conferida logada, rota respondendo, linha no banco.\n"
            'Não vale: "código pronto", "subiu", "200", "testes verdes".'
        )
    # Mesma trava para bloquear: o motivo é a única coisa que distingue
    # "travado esperando ele" de "esqueci e escondi da cobrança".
    if status == "bloqueada" and not a.nota:
        sys.exit(
            "bloquear exige --nota dizendo EM QUE está travada.\n"
            'Vale: "espera a resposta dele na #77", "precisa de perfil total".\n'
            'Não vale: "depois", "complicado", "sem tempo".'
        )
    # `--prazo` no despachar existe porque o prazo antigo continuaria valendo
    # depois do despacho, e o sweep cobraria de hora em hora um item que
    # tinha acabado de começar a ser feito. O relógio que importa é o do
    # trabalho em curso, não o da hora em que a promessa foi registrada.
    novo_prazo = prazo_para_data(getattr(a, "prazo", None))
    with conectar() as conn, conn.cursor() as c:
        fechado = "now()" if status in ("entregue", "cancelada") else "NULL"
        c.execute(
            f"UPDATE promessas SET status=%s, fechado_em={fechado}, "
            "nota=COALESCE(%s, nota), agent_id=COALESCE(%s, agent_id), "
            "prazo=COALESCE(%s, prazo) WHERE id=%s",
            (status, a.nota, getattr(a, "agent_id", None), novo_prazo, a.id),
        )
        conn.commit()
        print(f"promessa #{a.id} -> {status}" if c.rowcount else f"promessa #{a.id} não existe")


def abertas(conn):
    with conn.cursor() as c:
        c.execute(
            "SELECT id, criado_em, texto, dono, evidencia, prazo, status, nota "
            "FROM promessas WHERE status IN ('aberta','despachada','bloqueada') "
            "ORDER BY prazo NULLS LAST, id"
        )
        return c.fetchall()


def cmd_lista(_):
    with conectar() as c:
        linhas = abertas(c)
        if not linhas:
            print("nada em aberto")
            return
        agora = datetime.now(timezone.utc)
        for i, criado, texto, dono, _ev, prazo, status, _n in linhas:
            venceu = "VENCIDA" if prazo and prazo < agora else ""
            print(f"#{i:<4} {status:<11} {dono:<16} vence {brt(prazo):<12} {venceu:<8} {texto[:60]}")


def escrever_para_projetos(linhas):
    """O agente de projetos lê arquivo, não lê banco. Este é o arquivo dele,
    e ele é gerado, nunca escrito à mão: número escrito à mão apodrece."""
    agora = datetime.now(timezone.utc)
    out = [
        "# Promessas em aberto",
        "",
        "Gerado por `tools/promessas.py sweep`. **Não editar à mão**, o próximo",
        "sweep sobrescreve. Quem fecha item é a orquestradora, pelo comando, não pelo arquivo.",
        "",
        f"Atualizado em {agora.astimezone(BRT).strftime('%d/%m/%Y %H:%M')} (Brasília).",
        "",
    ]
    if not linhas:
        out += ["Nada em aberto.", ""]
    else:
        out += ["| # | prometida | vence | dono | estado | o que é | prova esperada | por que está travada |",
                "|---|---|---|---|---|---|---|---|"]
        for i, criado, texto, dono, ev, prazo, status, nota in linhas:
            venceu = " **VENCIDA**" if prazo and prazo < agora else ""
            # A coluna do motivo existe porque item bloqueado sem justificativa
            # escrita no banco não pode ser auditado por quem só lê o arquivo:
            # quem audita bloqueio sem enxergar a nota só está adivinhando. Só
            # aparece em `bloqueada` de propósito; nas outras a nota é
            # histórico de trabalho e ia poluir a tabela.
            motivo = (nota or "").replace("|", "/").replace("\n", " ") if status == "bloqueada" else ""
            if status == "bloqueada" and not motivo:
                motivo = "**SEM MOTIVO ESCRITO — cobrar a orquestradora**"
            out.append(
                f"| {i} | {brt(criado)} | {brt(prazo)}{venceu} | {dono} | {status} | "
                f"{texto} | {ev or 'não definida'} | {motivo[:400]} |"
            )
        out += ["", "**Prova esperada** é o que faz o item poder ser fechado: uma rota que",
                "responde, um campo na tela, uma linha no banco. Item sem prova definida",
                "não pode ser dado como entregue por ninguém.", ""]
    with open(ARQUIVO_PROJETOS, "w") as f:
        f.write("\n".join(out))


def cmd_sweep(_):
    with conectar() as c:
        linhas = abertas(c)
        escrever_para_projetos(linhas)
        agora = datetime.now(timezone.utc)
        # "bloqueada" continua APARECENDO na lista e no arquivo, de propósito:
        # nada sai do radar. O que ela não faz é gerar cobrança de hora em
        # hora, porque item travado esperando resposta do Chefe não é item
        # que ficou parado por descuido.
        vencidas = [l for l in linhas if l[5] and l[5] < agora and l[6] != "bloqueada"]
        # Só grita pelo que venceu. Cobrança de item no prazo vira ruído, e
        # aviso que vira ruído deixa de ser lido.
        if not vencidas:
            print(f"sweep ok, {len(linhas)} em aberto, nenhuma vencida")
            return
        resumo = "; ".join(f"#{l[0]} {l[2][:50]} (dono {l[3]})" for l in vencidas[:5])
        # Poucos itens vencidos não justificam acionar um subagente inteiro
        # (sem cache, recarrega tudo do zero) só pra conferir 1 ou 2 coisas.
        # A ordem é explícita: pouco item com prova fácil, confere a própria
        # orquestradora; volume alto, aí sim delega em bloco.
        orientacao = (
            "Confira você mesma, na sessão principal, sem acionar subagente."
            if len(vencidas) < 3 else
            "Volume alto, delegar pro agente de projetos investigar em bloco faz sentido aqui."
        )
        msg = (
            f"[sistema] PROMESSA VENCIDA: {len(vencidas)} item(ns) passaram do prazo "
            f"sem entrega confirmada. {resumo}. {orientacao} Feche com "
            f"tools/promessas.py entregar, e se ainda nao despachou, despache agora."
        )
        subprocess.run([INJECT, msg], check=False)
        print(f"sweep: {len(vencidas)} vencida(s), cobrança injetada")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add")
    a.add_argument("texto")
    a.add_argument("--dono", default="{{AGENTE_NAME_LOWERCASE}}")
    a.add_argument("--evidencia")
    a.add_argument("--prazo")
    a.add_argument("--msg-id", dest="msg_id")
    a.add_argument("--despachada", action="store_true",
                   help="nasce despachada: use quando voce ja esta chamando o agente agora")
    a.set_defaults(fn=cmd_add)

    for nome, status in [("despachar", "despachada"), ("entregar", "entregue"),
                         ("cancelar", "cancelada"), ("bloquear", "bloqueada")]:
        s = sub.add_parser(nome)
        s.add_argument("id", type=int)
        s.add_argument("--nota")
        s.add_argument("--agent-id", dest="agent_id")
        s.add_argument("--prazo", help="reposiciona o prazo (ex: 2h). Use ao despachar: o relogio conta do inicio do trabalho")
        s.set_defaults(fn=lambda x, st=status: cmd_estado(x, st))

    sub.add_parser("lista").set_defaults(fn=cmd_lista)
    sub.add_parser("sweep").set_defaults(fn=cmd_sweep)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
