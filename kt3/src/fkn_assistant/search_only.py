"""Reference variant with the same filters and forms, using a source excerpt as the answer."""

from fkn_assistant.forms import result
from fkn_assistant.rag import Rag


class SearchOnly(Rag):
    def __init__(self, search, threshold):
        super().__init__(search, None, threshold=threshold)

    def generate(self, text, profile, now, history, hits, steps, trace, deadline):
        steps.take("quote")
        hit = hits[0]
        trace["context"] = [hit]
        answer = result("answer_partial", "rag_answer", hit["text"][:740])
        answer["citations"] = [
            {
                key: hit[key]
                for key in (
                    "doc_id",
                    "clause_id",
                    "version",
                    "source_url",
                    "path",
                    "citation_id",
                )
            }
        ]
        return answer
