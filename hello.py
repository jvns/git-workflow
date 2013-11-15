from flask import Flask, render_template, jsonify, request
import pandas as pd
import networkx as nx
import pygraphviz as pgv

app = Flask(__name__)
app.config['DEBUG'] = True

@app.route('/')
def hello():
    return render_template('index.html', name="Julia")

@app.route('/graph', methods=["POST"])
def get_image():
    history = request.form["history"]
    pair_counts = get_statistics(history)
    G = create_graph(pair_counts[:20])
    response = {'graph': dot_draw(G, tmp_dir="./tmp")}
    return jsonify(response)

def dot_draw(G, prog="circo", tmp_dir="/tmp"):
    # Hackiest code :)
    tmp_dot = tempfile.mktemp(dir=tmp_dir, suffix=".dot")
    tmp_image = tempfile.mktemp(dir=tmp_dir, suffix=".png")
    nx.write_dot(G, tmp_dot)
    dot_graph = pgv.AGraph(tmp_dot)
    dot_graph.draw(tmp_image, prog=prog)
    with open(tmp_image) as f:
        data = f.read()
    return data.encode("base64")

def getwidth(node, totals):
    count = np.sqrt(node_totals[node])
    count /= float(sum(np.sqrt(node_totals)))
    count *= 20
    count = max(count, 0.3)
    count = min(count, 4)
    return count

def get_colors(nodes):
    n_colors = 8
    colors = {}
    set2 = brewer2mpl.get_map('Dark2', 'qualitative', n_colors).hex_colors
    for i, node in enumerate(nodes):
        colors[node] = set2[i % n_colors]
    return colors

def create_graph(pair_counts):
    G = nx.DiGraph()
    node_colors = get_colors(list(node_totals.index))
    for (frm, to), count in pair_counts.iterrows():
        G.add_edge(frm, to, penwidth=float(count) / 8, color=node_colors[frm])
    for node in G.nodes():
        G.node[node]['width'] = getwidth(node, node_totals)
        G.node[node]['height'] = G.node[node]['width']
        G.node[node]['color'] = node_colors[node]
        G.node[node]['label'] = "%s (%d%%)" % (node, int(node_totals[node] / float(sum(node_totals)) * 100) )
    return G

def get_statistics(text):
    df = pd.read_csv(text, sep=' ', header=None, names=["row", "command"], index_col="row")
    pairs = pd.DataFrame(index=range(len(df) - 1))
    pairs['dist'] = df.index[1:].values - df.index[:-1].values
    pairs['from'] = df['command'][:-1].values
    pairs['to'] = df['command'][1:].values
    close_pairs = pairs[pairs.dist == 1]
    pair_counts = close_pairs.groupby(['from', 'to']).aggregate(len).rename(columns= {'dist': 'count'})
    pair_counts = pair_counts.sort('count', ascending=False)
    return pair_counts
