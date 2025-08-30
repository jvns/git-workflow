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


@app.route("/image/<num>/git-workflow.png")
def serve_image(num=None):
    return serve_image_inner(num)

@app.route("/image/sparse/<num>/git-workflow.png")
def serve_image_sparse(num=None):
    return serve_image_inner(num, sparse=True)

def serve_image_inner(num, sparse=False):
    cursor = g.conn.cursor()
    cursor.execute(
        "SELECT row_number, command FROM entries WHERE log_id = ? ORDER BY row_number",
        (num,),
    )
    entries = cursor.fetchall()
    if not entries:
        return "Graph is empty!", 404
    image = create_image(entries, format='png', sparse=sparse)
    return Response(image, mimetype="image/png")

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
    # colorbrewer Dark2 color scheme + lighter fill colours
    color_palette = [
        {"color": "#3b82f6", "fill": "#eff6ff"},
        {"color": "#f59e0b", "fill": "#fffbeb"},
        {"color": "#ec4899", "fill": "#fdf2f8"},
        {"color": "#8b5cf6", "fill": "#f5f3ff"},
        {"color": "#10b981", "fill": "#f0fdf4"},
        {"color": "#f97316", "fill": "#fff7ed"},
        {"color": "#64748b", "fill": "#f8fafc"},
        {"color": "#ef4444", "fill": "#fef2f2"},
    ]
    return {node: color_palette[i % len(color_palette)] for i, node in enumerate(nodes)}

def create_image(entries, format, sparse):
    pair_counts, node_totals = get_statistics(entries, sparse)
    return create_image_inner(pair_counts, node_totals, format)

def create_image_inner(pair_counts, node_totals, format="svg"):
    dot = graphviz.Digraph()
    dot.attr(
        rankdir="TB",
        bgcolor="#fef5e7",
        pad="0.2",
        fontname="Arial,Helvetica,system-ui,sans-serif",
        fontsize="12",
        fontcolor="#656d76",
        label="Visualize Your Git: gitviz.jvns.ca",
        labelloc="b",
        labeljust="r",
        dpi="200"
    )

    # Make a subgraph for aesthetics
    graph = graphviz.Digraph(name='cluster_main')
    graph.attr(
        style="filled,rounded",
        fillcolor="white",
        pencolor="#f6ad55",
        penwidth="1.5",
        margin="15",
        label=""
    )

    # Extract nodes
    nodes = set()
    for (frm, to), row in pair_counts.iterrows():
        nodes.add(frm)
        nodes.add(to)
    # Sort to make colorscheme deterministic
    nodes = list(sorted(nodes))

    node_colors = build_colorscheme(nodes)

    # Add nodes
    for node in nodes:
        size = np.sqrt(node_totals[node])
        size /= float(sum(np.sqrt(node_totals)))
        size *= 6
        size = max(size, 0.1)
        size = min(size, 4)
        width = max(size, 0.7)

        percentage = int(node_totals[node] / float(sum(node_totals)) * 100)

        graph.node(
            node,
            shape="box",
            style="filled,rounded",
            fontname="Inconsolata, monospace",
            fillcolor=node_colors[node]["fill"],
            color=node_colors[node]["color"],
            label=f"{node}\\n{percentage}%",
            width=str(width),
            height=str(size),
            fontsize="12",
            penwidth="1.5",
            margin="0.15"
        )

    # Add edges
    total_count = np.sum(pair_counts["count"])
    for (frm, to), row in pair_counts.iterrows():
        size = row["count"]
        penwidth = min(float(size) / total_count * 60, 10)
        arrowsize = 1.0
        if penwidth  > 5:
            arrowsize = 0.1
        graph.edge(
            frm,
            to,
            penwidth=str(penwidth),
            color=node_colors[frm]["color"],
            arrowsize=str(arrowsize),
        )

    # Add the cluster to the main graph
    dot.subgraph(graph)

    return dot.pipe(format=format, encoding="utf-8" if format == "svg" else None)


def get_statistics(entries, sparse=False):
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
    total_count = float(np.sum(pair_counts["count"]))

    # In sparse mode, only include transitions that happen at
    # least 1% of the time
    min_count = 1
    if sparse:
        min_count = total_count / 100
    elif total_count >= 1000:
        min_count = 5
    pair_counts = pair_counts[pair_counts["count"] >= min_count]

    return pair_counts, node_totals


@app.before_request
def before():
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
