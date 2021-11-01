import collections

import torch

from transition_amr_parser.io import read_amr2


def safe_read(path, ibm_format=True, tokenize=False, max_length=0, check_for_edges=False, remove_empty_align=True, remove_none_edges=True):

    skipped = collections.Counter()

    corpus = read_amr2(path, ibm_format=ibm_format, tokenize=tokenize)

    if max_length > 0:
        new_corpus = []
        for amr in corpus:
            if len(amr.tokens) > max_length:
                skipped['max-length'] += 1
                continue
            new_corpus.append(amr)
        corpus = new_corpus

    if check_for_edges:
        new_corpus = []
        for amr in corpus:
            if len(amr.edges) == 0:
                skipped['no-edges'] += 1
                continue
            new_corpus.append(amr)
        corpus = new_corpus

    if remove_none_edges:
        for amr in corpus:
            new_edges = []
            for e in amr.edges:
                s, y, t = e
                if t not in amr.nodes:
                    print('Warning: Node does not exist. node = {}, amr = {}'.format(t, amr))
                    continue
                new_edges.append(e)
            amr.edges = new_edges

    if remove_empty_align and corpus[0].alignments is not None:
        stats = collections.Counter()

        for amr in corpus:
            node_ids = list(amr.alignments.keys())
            for k in node_ids:
                if amr.alignments[k] is None:
                    del amr.alignments[k]
                    stats['is-none'] += 1
                elif k not in amr.nodes:
                    del amr.alignments[k]
                    stats['is-not-node'] += 1
                else:
                    stats['exists'] += 1
        print('remove_empty_align: {}'.format(stats))

    # Check
    for amr in corpus:
        assert len(amr.tokens) > 0
        assert amr.root is not None

    print('read {}, total = {}, skipped = {}'.format(path, len(corpus), skipped))

    return corpus


def get_node_ids(amr):
    return list(sorted(amr.nodes.keys()))


def get_tree_edges(amr):

    node_TO_edges = collections.defaultdict(list)
    for e in amr.edges:
        s, y, t = e
        node_TO_edges[s].append(e)

    new_edges = []

    seen = set()
    seen.add(amr.root)

    def helper(root, prefix='0'):
        if root not in node_TO_edges:
            return

        for i, e in enumerate(node_TO_edges[root]):
            s, y, t = e
            assert s == root
            if t in seen:
                continue
            seen.add(t)
            new_prefix = '{}.{}'.format(prefix, i)
            new_e = (s, y, t, prefix, new_prefix)
            new_edges.append(new_e)
            helper(t, prefix=new_prefix)

    helper(amr.root)

    return new_edges


def convert_amr_to_tree(amr):

    tree = {}
    tree['root'] = amr.root
    tree['node_to_children'] = collections.defaultdict(list)
    tree['edge_to_label'] = {}
    tree['edges'] = []
    tree['node_ids'] = get_node_ids(amr)

    safe_edges = get_tree_edges(amr)

    def sortkey(x):
        s, y, t, a, b = x
        return (a, b)

    for e in sorted(safe_edges, key=sortkey):
        s, y, t, a, b = e
        assert a <= b

        tree['node_to_children'][s].append(t)
        tree['edge_to_label'][(s, t)] = y
        tree['edges'].append((s, t))

    return tree


def compute_pairwise_distance(tree):
    node_ids = tree['node_ids']
    node_TO_idx = {k: i for i, k in enumerate(node_ids)}

    n_a = len(node_ids)
    d = torch.zeros(n_a, n_a, dtype=torch.long)

    def helper(root):
        """ Compute pairwise distance between all descendants.
            Also includes distance to root.
        """
        children = tree['node_to_children'][root]

        if len(children) == 0:
            return [(root, 1)]

        # This contains [[(node_id, distance_to_root)]]
        descendants = []

        for x in children:
            x_descendants = helper(x)
            descendants.append(x_descendants)

        # Compute distance between children.
        for i, i_list in enumerate(descendants):
            for j, j_list in enumerate(descendants):
                if i == j:
                    continue

                for (i_node, i_root_dist) in i_list:
                    for (j_node, j_root_dist) in j_list:
                        i_node_id = node_TO_idx[i_node]
                        j_node_id = node_TO_idx[j_node]
                        assert d[i_node_id, j_node_id].item() == 0
                        d[i_node_id, j_node_id] = i_root_dist + j_root_dist


        # Compute distance from children to root.
        new_descendants = []
        j_node = root
        j_node_id = node_TO_idx[j_node]
        for i_list in descendants:
            for (i_node, i_root_dist) in i_list:
                i_node_id = node_TO_idx[i_node]

                assert d[i_node_id, j_node_id].item() == 0
                d[i_node_id, j_node_id] = i_root_dist

                assert d[j_node_id, i_node_id].item() == 0
                d[j_node_id, i_node_id] = i_root_dist

                new_descendants.append((i_node, i_root_dist + 1))

        new_descendants.append((root, 1))

        return new_descendants

    _ = helper(tree['root'])

    assert torch.all(d == d.transpose(0, 1)).item()

    return d
