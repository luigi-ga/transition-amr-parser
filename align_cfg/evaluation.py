import collections

from amr_utils import convert_amr_to_tree, compute_pairwise_distance, get_node_ids
from amr_utils import read_amr

import numpy as np


def format_value(val):
    if isinstance(val, float):
        return '{:.3f}'.format(val)
    return val


class Metric(object):
    _name = None

    @property
    def name(self):
        return self._name

    def __init__(self):
        self.state = collections.defaultdict(list)

    def update(self, gold, pred):
        raise NotImplementedError

    def finish(self):
        raise NotImplementedError

    def print(self, result):
        header = '{}'.format(self.name)
        underl = '-' * len(header)
        output = '{}\n{}\n'.format(header, underl)
        for k, v in result.items():
            output += '- {} = {}\n'.format(k, format_value(v))
        print(output)


class MAPImpliedDistance(Metric):
    _name = 'MAP Implied Distance'

    def update(self, gold, pred):
        tree = convert_amr_to_tree(gold)
        pairwise_dist = compute_pairwise_distance(tree)
        node_ids = tree['node_ids']
        n = len(node_ids)

        def helper(amr, max_amr_dist=0):
            res = []

            # TODO: Adjust for spans.
            # TODO: Vectorize.
            for i in range(n):
                if node_ids[i] not in amr.alignments:
                    continue

                k = amr.alignments[node_ids[i]][0] - 1

                for j in range(i + 1, n):
                    if node_ids[j] not in amr.alignments:
                        continue

                    l = amr.alignments[node_ids[j]][0] - 1

                    amr_dist = pairwise_dist[i, j].item()

                    if max_amr_dist > 0 and amr_dist > max_amr_dist:
                        continue

                    tok_dist = np.abs(k - l).item()
                    sq_diff = np.power(tok_dist - amr_dist, 2)
                    res.append(sq_diff)

            return res

        self.state['gold'].append(np.sum(helper(gold)))
        self.state['gold_max_3'].append(np.sum(helper(gold, max_amr_dist=3)))
        self.state['pred'].append(np.sum(helper(pred)))
        self.state['pred_max_3'].append(np.sum(helper(pred, max_amr_dist=3)))

    def finish(self):
        result = dict()
        result['pred'] = np.mean(self.state['pred']).item()
        result['pred_max_3'] = np.mean(self.state['pred_max_3']).item()
        result['gold'] = np.mean(self.state['gold']).item()
        result['gold_max_3'] = np.mean(self.state['gold_max_3']).item()
        return result


class SentenceRecall(Metric):
    _name = 'Sentence Recall'

    def update(self, gold, pred):
        gold_align, pred_align = gold.alignments, pred.alignments
        total, correct = 0, 0

        for node_id in gold_align.keys():
            p = pred_align[node_id]
            g = gold_align[node_id]

            total += 1

            if p == g:
                correct += 1

        # Don't count examples without alignments.
        if total == 0:
            return

        recall = correct / total

        self.state['recall'].append(recall)

    def finish(self):
        result = dict(recall=np.mean(self.state['recall']).item())
        return result


class CorpusRecall(Metric):
    _name = 'Corpus Recall'

    def update(self, gold, pred):
        gold_align, pred_align = gold.alignments, pred.alignments
        total, correct = 0, 0

        for node_id in gold_align.keys():
            p = pred_align[node_id][0] - 1
            g = gold_align[node_id][0] - 1

            total += 1

            if p == g:
                correct += 1

        self.state['total'].append(total)
        self.state['correct'].append(correct)

    def finish(self):
        total = np.sum(self.state['total']).item()
        correct = np.sum(self.state['correct']).item()
        recall = correct / total

        result = collections.OrderedDict()
        result['correct'] = correct
        result['total'] = total
        result['recall'] = recall

        return result


class CorpusRecall_ExcludeNode(CorpusRecall):
    def __init__(self, exclude=['country', 'name', 'person']):
        super().__init__()

        self.exclude = exclude

    @property
    def name(self):
        return '{} excluding nodes = {}'.format(self._name, ', '.join(["'{}'".format(x) for x in self.exclude]))

    def update(self, gold, pred):
        gold_align, pred_align = gold.alignments, pred.alignments
        total, correct, skipped = 0, 0, 0

        for node_id in gold_align.keys():
            node_name = gold.nodes[node_id]
            if node_name in self.exclude:
                skipped += 1
                continue

            p = pred_align[node_id][0] - 1
            g = gold_align[node_id][0] - 1

            total += 1

            if p == g:
                correct += 1

        self.state['total'].append(total)
        self.state['correct'].append(correct)
        self.state['skipped'].append(skipped)

    def finish(self):
        result = super().finish()
        result['skipped'] = np.sum(self.state['skipped']).item()
        return result


class CorpusRecall_DuplicateText(CorpusRecall):

    @property
    def name(self):
        return '{} with fixed duplicate text'.format(self._name)

    def update(self, gold, pred):
        gold_align, pred_align = gold.alignments, pred.alignments
        total, correct = 0, 0
        duplicate = 0
        fixed = 0

        text_counts = collections.Counter(gold.tokens)

        for node_id in gold_align.keys():
            p = pred_align[node_id][0] - 1
            g = gold_align[node_id][0] - 1

            text_name = gold.tokens[g]
            if text_counts[text_name] > 1:
                duplicate += 1

                if p != g:
                    fixed += 1
                    p = g

            total += 1

            if p == g:
                correct += 1

        self.state['total'].append(total)
        self.state['correct'].append(correct)
        self.state['duplicate'].append(duplicate)
        self.state['fixed'].append(fixed)

    def finish(self):
        result = super().finish()
        result['duplicate'] = np.sum(self.state['duplicate']).item()
        result['fixed'] = np.sum(self.state['fixed']).item()
        return result


class CorpusRecall_IgnoreURL(CorpusRecall):

    @property
    def name(self):
        return '{} ignoring URLs'.format(self._name)

    def update(self, gold, pred):
        sentence = ' '.join(gold.tokens)

        if 'http' in sentence:
            self.state['skipped'].append(1)
            return

        gold_align, pred_align = gold.alignments, pred.alignments
        total, correct = 0, 0

        for node_id in gold_align.keys():
            p = pred_align[node_id][0] - 1
            g = gold_align[node_id][0] - 1

            total += 1

            if p == g:
                correct += 1

        self.state['total'].append(total)
        self.state['correct'].append(correct)

    def finish(self):
        result = super().finish()
        result['skipped'] = np.sum(self.state['skipped']).item()
        return result


class CorpusRecall_WithGoldSpans(CorpusRecall):

    @property
    def name(self):
        return '{} using spans for gold'.format(self._name)

    def update(self, gold, pred):
        gold_align, pred_align = gold.alignments, pred.alignments
        total, correct = 0, 0

        for node_id in gold_align.keys():
            assert len(pred_align[node_id]) == 1
            p = pred_align[node_id][0] - 1

            g0 = gold_align[node_id][0] - 1
            g1 = gold_align[node_id][-1] - 1

            total += 1

            if (p >= g0) and (p <= g1):
                correct += 1

        self.state['total'].append(total)
        self.state['correct'].append(correct)


class CorpusRecall_WithDupsAndSpans(CorpusRecall):

    @property
    def name(self):
        return '{} with dups and spans'.format(self._name)

    def update(self, gold, pred):
        gold_align, pred_align = gold.alignments, pred.alignments
        total, correct = 0, 0

        text_counts = collections.Counter(gold.tokens)

        is_span = False
        is_duplicate = False
        is_fixed = False

        for node_id in gold_align.keys():
            assert len(pred_align[node_id]) == 1
            p = pred_align[node_id][0] - 1

            g0 = gold_align[node_id][0] - 1
            g1 = gold_align[node_id][-1] - 1

            if len(gold_align[node_id]) > 0:
                is_span = True

            is_correct = False
            if (p >= g0) and (p <= g1):
                is_correct = True

            text_name = gold.tokens[g0]
            if text_counts[text_name] > 1:
                is_duplicate = True

                if not is_correct:
                    is_correct = True
                    is_fixed = True

            if is_correct:
                correct += 1

            total += 1

        is_duplicate_and_fixed = is_duplicate and is_fixed
        is_both = is_span and is_duplicate
        is_both_and_fixed = is_both and is_fixed

        def to_int(b):
            return 1 if b else 0

        self.state['total'].append(total)
        self.state['correct'].append(correct)
        self.state['is_duplicate'].append(to_int(is_duplicate))
        self.state['is_duplicate_and_fixed'].append(to_int(is_duplicate_and_fixed))
        self.state['is_span'].append(to_int(is_span))
        self.state['is_both'].append(to_int(is_both))
        self.state['is_both_and_fixed'].append(to_int(is_both_and_fixed))

    def finish(self):
        result = super().finish()
        for k in ['is_duplicate', 'is_duplicate_and_fixed', 'is_span', 'is_both', 'is_both_and_fixed']:
            result[k] = np.sum(self.state[k]).item()
        return result


class EvalAlignments(object):
    def run(self, path_gold, path_pred, verbose=True):

        metrics = [
            # MAPImpliedDistance(),
            SentenceRecall(),
            CorpusRecall(),
            CorpusRecall_ExcludeNode(),
            CorpusRecall_DuplicateText(),
            CorpusRecall_IgnoreURL(),
            CorpusRecall_WithGoldSpans(),
            CorpusRecall_WithDupsAndSpans(),
        ]

        gold = read_amr(path_gold).amrs
        pred = read_amr(path_pred).amrs

        assert len(gold) == len(pred)

        for g, p in zip(gold, pred):

            for m in metrics:
                m.update(g, p)

        if verbose:
            # clear line
            print('')

        output = {}

        for m in metrics:
            result = m.finish()
            if verbose:
                m.print(result)
            output[m.name] = result

        return output
