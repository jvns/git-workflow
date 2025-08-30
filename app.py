from flask import (
    Flask,
    render_template,
    jsonify,
    request,
    g,
    redirect,
    url_for,
    Response,
)
import pandas as pd
import graphviz
import numpy as np
from io import StringIO
import sqlite3
import os
from nanoid import generate


app = Flask(__name__)
app.config["DEBUG"] = True


def load_valid_commands():
    with open("commands.txt", "r") as f:
        return set(line.strip() for line in f)


VALID_GIT_COMMANDS = load_valid_commands()


@app.route("/")
def hello():
    return render_template("index.html")


@app.route("/review/<log_id>")
def review_commands(log_id):
    cursor = g.conn.cursor()
    cursor.execute(
        "SELECT DISTINCT command FROM entries WHERE log_id = ? AND valid = 0", (log_id,)
    )
    invalid_commands = [row[0] for row in cursor.fetchall()]
    return render_template(
        "review_commands.html", log_id=log_id, invalid_commands=invalid_commands
    )


@app.route("/review/<log_id>/clean", methods=["POST"])
def clean_commands(log_id):
    cursor = g.conn.cursor()
    cursor.execute("DELETE FROM entries WHERE log_id = ? AND valid = 0", (log_id,))
    g.conn.commit()
    return redirect(url_for("display_graph", num=log_id))


@app.route("/review/<log_id>/keep", methods=["POST"])
def keep_commands(log_id):
    return redirect(url_for("display_graph", num=log_id))


@app.route("/display/<num>")
def display_graph(num=None):
    return render_template("display_graph.html", num=num)


@app.route("/svg/<num>")
def serve_svg(num=None):
    sparse = request.args.get("sparse", False)
    cursor = g.conn.cursor()
    cursor.execute(
        "SELECT row_number, command FROM entries WHERE log_id = ? ORDER BY row_number",
        (num,),
    )
    entries = cursor.fetchall()
    if not entries:
        return "Graph is empty!", 404
    svg = create_svg(entries, sparse=sparse)
    return Response(svg, mimetype="image/svg+xml")


def create_svg(entries, sparse=False):
    pair_counts, node_totals = get_statistics(entries)
    if pair_counts.empty:
        return None
    total_count = float(np.sum(pair_counts["count"]))
    # Only look at transitions that happen at least 1% of the time
    min_count = 1
    if sparse:
        min_count = total_count / 100
    elif total_count >= 1000:
        min_count = 5
    counts = pair_counts[pair_counts["count"] >= min_count]
    if len(counts) == 0:
        return
    return create_graph_svg(counts, node_totals)


@app.route("/graph", methods=["POST"])
def get_image():
    history = request.form["history"]
    log_id = save_history(history)

    # Delete invalid commands that only appear once or start with dash
    # (probably typos or flags)
    cursor = g.conn.cursor()
    cursor.execute(
        """
        DELETE FROM entries
        WHERE log_id = ? AND valid = 0
        AND (
            command = 'git'
            OR command LIKE '-%'
            OR command IN (
                SELECT command
                FROM entries
                WHERE log_id = ? AND valid = 0
                GROUP BY command
                HAVING COUNT(*) = 1
            )
        )
    """,
        (log_id, log_id),
    )
    g.conn.commit()

    # Check if there are still invalid commands
    cursor.execute(
        "SELECT COUNT(*) FROM entries WHERE log_id = ? AND valid = 0", (log_id,)
    )
    invalid_count = cursor.fetchone()[0]

    if invalid_count > 0:
        return redirect(url_for("review_commands", log_id=log_id))
    else:
        return redirect(url_for("display_graph", num=log_id))


def save_history(history):
    cursor = g.conn.cursor()
    log_id = generate(
        alphabet="0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz",
        size=10,
    )
    cursor.execute("INSERT INTO logs (id) VALUES (?);", (log_id,))

    lines = [l for l in history.split("\n") if len(l.strip()) > 0]
    for line in lines:
        parts = line.strip().split(" ", 1)
        if len(parts) != 2:
            continue
        row_number, command = parts
        cursor.execute(
            "INSERT INTO entries (log_id, row_number, command, valid) VALUES (?, ?, ?, ?);",
            (log_id, int(row_number), command, command in VALID_GIT_COMMANDS),
        )

    g.conn.commit()
    return log_id


def build_colorscheme(nodes):
    # colorbrewer Dark2 color scheme
    color_palette = [
        "#1b9e77",
        "#d95f02",
        "#7570b3",
        "#e7298a",
        "#66a61e",
        "#e6ab02",
        "#a6761d",
        "#666666",
    ]
    return {node: color_palette[i % len(color_palette)] for i, node in enumerate(nodes)}


def create_graph_svg(pair_counts, node_totals):

    dot = graphviz.Digraph()
    dot.attr(rankdir="TB")

    # Extract nodes
    nodes = set()
    for (frm, to), row in pair_counts.iterrows():
        nodes.add(frm)
        nodes.add(to)
    nodes = list(nodes)

    node_colors = build_colorscheme(nodes)

    # Add nodes
    for node in nodes:
        size = np.sqrt(node_totals[node])
        size /= float(sum(np.sqrt(node_totals)))
        size *= 6
        size = max(size, 0.1)
        size = min(size, 4)

        percentage = int(node_totals[node] / float(sum(node_totals)) * 100)

        dot.node(
            node,
            label=f"{node} ({percentage}%)",
            color=node_colors[node],
            width=str(size),
            height=str(size),
            fontsize="10",
            penwidth="2",
        )

    # Add edges
    total_count = np.sum(pair_counts["count"])
    for (frm, to), row in pair_counts.iterrows():
        size = row["count"]
        penwidth = min(float(size) / total_count * 60, 10)
        arrowsize = "1"
        if penwidth > 5:
            arrowsize = "0.1"
        dot.edge(
            frm, to, penwidth=str(penwidth), color=node_colors[frm], arrowsize=arrowsize
        )

    return dot.pipe(format="svg", encoding="utf-8")


def get_statistics(entries):
    df = pd.DataFrame(entries, columns=["row", "command"]).set_index("row")
    pairs = pd.DataFrame(index=range(len(df) - 1))
    pairs["dist"] = df.index[1:].values - df.index[:-1].values
    pairs["from"] = df["command"][:-1].values
    pairs["to"] = df["command"][1:].values
    node_totals = df["command"].value_counts()
    close_pairs = pairs[pairs.dist == 1]
    pair_counts = (
        close_pairs.groupby(["from", "to"])
        .aggregate(len)
        .rename(columns={"dist": "count"})
    )
    pair_counts = pair_counts.sort_values("count", ascending=False)
    return pair_counts, node_totals


@app.before_request
def before():
    try:
        os.mkdir("tmp")
    except OSError:
        pass
    g.conn = db_connect()


@app.teardown_request
def teardown_request(exception):
    db = getattr(g, "db", None)
    if db is not None:
        db.close()


def db_connect():
    db_path = os.environ.get("DATABASE_PATH", "git_workflow.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Create tables if they don't exist
    with open("schema.sql", "r") as f:
        schema = f.read()
    conn.executescript(schema)
    conn.commit()

    return conn


if __name__ == "__main__":
    app.run(port=5001)
