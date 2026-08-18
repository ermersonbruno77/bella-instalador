#!/usr/bin/env python3
"""Registro de delegação a subagente.

Toda delegação passa por aqui. A regra: registrar ANTES de chamar o subagente e
encerrar assim que ele responder. Se você esquecer de encerrar, a tarefa fica
"rodando" para sempre e o painel mostra isso, o que é melhor do que apagar o
rastro.

Uso:
    # ao delegar (imprime o id, que você usa para encerrar)
    python3 tools/agente_log.py inicio paulo-dev "arrumar a pagina de caixa do painel"

    # ao receber o resultado
    python3 tools/agente_log.py fim <id> ok "reescrita em cards, 3 arquivos"
    python3 tools/agente_log.py fim <id> falha "nao consegui, VPN fora"

    # opcional: arquivos tocados, separados por virgula
    python3 tools/agente_log.py fim <id> ok "pronto" --arquivos web/app/caixa/page.tsx,web/lib/tipos.ts

    # passo intermediário, enquanto a tarefa ainda está rodando (dá vida ao
    # painel de agentes: é o texto que aparece no balão do bonequinho)
    python3 tools/agente_log.py passo <id> "conferindo o consolidado"

    # ver o que está rodando agora
    python3 tools/agente_log.py agora
"""
import os
import sys

import psycopg2
import psycopg2.extras

DSN = os.environ.get(
    "DATABASE_URL", "postgresql://{{AGENTE_NAME_LOWERCASE}}@127.0.0.1:5432/{{AGENTE_NAME_LOWERCASE}}_memory"
)
STATUS_FINAL = ("ok", "falha", "cancelado")


def conectar():
    return psycopg2.connect(DSN)


def cmd_inicio(agente, tarefa, frente=None):
    with conectar() as con, con.cursor() as cur:
        cur.execute(
            "INSERT INTO agente_atividade(agente, tarefa, sessao, frente)"
            " VALUES (%s, %s, %s, %s) RETURNING id",
            (agente, tarefa, os.environ.get("AGENTE_SESSAO"), frente),
        )
        print(cur.fetchone()[0])
    return 0


def cmd_fim(ident, status, resultado, arquivos=None, tokens=None):
    if status not in STATUS_FINAL:
        print(f"status inválido: {status}. use um de {', '.join(STATUS_FINAL)}")
        return 1
    with conectar() as con, con.cursor() as cur:
        cur.execute(
            """UPDATE agente_atividade
                  SET terminado_em = now(), status = %s, resultado = %s,
                      arquivos = COALESCE(%s, arquivos),
                      tokens = COALESCE(%s, tokens)
                WHERE id = %s AND terminado_em IS NULL
             RETURNING agente""",
            (status, resultado, arquivos, tokens, ident),
        )
        linha = cur.fetchone()
    if not linha:
        # Não invento sucesso: ou o id não existe, ou já estava encerrado.
        print(f"nada a encerrar no id {ident} (inexistente ou já fechado)")
        return 1
    print(f"encerrado: {linha[0]} #{ident} -> {status}")
    return 0


def cmd_passo(atividade_id, texto):
    with conectar() as con, con.cursor() as cur:
        # Só registra passo em atividade que existe e ainda está aberta — não
        # faz sentido reportar progresso de algo que já fechou, e um id
        # inventado não pode criar rastro de trabalho que não houve.
        cur.execute(
            "SELECT 1 FROM agente_atividade WHERE id = %s AND terminado_em IS NULL",
            (atividade_id,),
        )
        if not cur.fetchone():
            print(f"id {atividade_id} não existe ou já está encerrado; passo não gravado")
            return 1
        cur.execute(
            "INSERT INTO agente_atividade_passo(atividade_id, texto) VALUES (%s, %s) RETURNING id",
            (atividade_id, texto),
        )
        print(cur.fetchone()[0])
    return 0


def cmd_agora():
    with conectar() as con, con.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        cur.execute(
            """SELECT id, agente, tarefa, iniciado_em,
                      round(extract(epoch from (now() - iniciado_em)) / 60) AS minutos
                 FROM agente_atividade
                WHERE terminado_em IS NULL
                ORDER BY iniciado_em"""
        )
        linhas = cur.fetchall()
    if not linhas:
        print("nenhum agente rodando")
        return 0
    for r in linhas:
        print(f"#{r['id']} {r['agente']}: {r['tarefa']} (há {int(r['minutos'])} min)")
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    if cmd == "inicio":
        if len(sys.argv) < 4:
            print("uso: inicio <agente> <tarefa> [--frente Nome]")
            return 1
        frente = None
        if "--frente" in sys.argv:
            i = sys.argv.index("--frente")
            if i + 1 < len(sys.argv):
                frente = sys.argv[i + 1].strip() or None
        return cmd_inicio(sys.argv[2], sys.argv[3], frente)
    if cmd == "fim":
        if len(sys.argv) < 5:
            print("uso: fim <id> <ok|falha|cancelado> <resultado> [--arquivos a,b] [--tokens N]")
            return 1
        arquivos = None
        if "--arquivos" in sys.argv:
            i = sys.argv.index("--arquivos")
            if i + 1 < len(sys.argv):
                arquivos = [a.strip() for a in sys.argv[i + 1].split(",") if a.strip()]
        # `--tokens` NUNCA fica de fora: o número está sempre no retorno do
        # próprio subagente. Sem ele, a execução entra no painel como "sem
        # token" e o consumo real fica invisível.
        tokens = None
        if "--tokens" in sys.argv:
            i = sys.argv.index("--tokens")
            if i + 1 < len(sys.argv):
                try:
                    tokens = int(str(sys.argv[i + 1]).replace(".", "").replace(",", ""))
                except ValueError:
                    print("--tokens precisa ser número inteiro; ignorando")
        return cmd_fim(int(sys.argv[2]), sys.argv[3], sys.argv[4], arquivos, tokens)
    if cmd == "passo":
        if len(sys.argv) < 4:
            print("uso: passo <id> <texto curto>")
            return 1
        return cmd_passo(int(sys.argv[2]), sys.argv[3])
    if cmd == "agora":
        return cmd_agora()
    print(f"comando desconhecido: {cmd}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
