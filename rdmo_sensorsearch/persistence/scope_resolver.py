"""The single boundary between scalar reconciliation and RDMO's AnswerTree."""

from inspect import signature

from rdmo_sensorsearch.services.performance import measure_phase


def _build_answer_tree(catalog, values, factory):
    # The new constructor accepts a second positional argument as `verbose`.
    # Trying both calls would silently pass Values as verbosity settings.
    parameters = signature(factory).parameters
    if "values" in parameters:
        return factory(catalog, values)
    if "catalog" not in parameters or "values" not in signature(factory.compute).parameters:
        raise TypeError("Unsupported RDMO AnswerTree API.")
    tree = factory(catalog)
    tree.compute(values)
    return tree


class RDMOAnswerTreeScopeResolver:
    """Reuse one live-value index and cache lookups for one reconciliation."""

    @measure_phase("scalar.scope_setup")
    def __init__(self, project, *, answer_tree_factory=None):
        if answer_tree_factory is None:
            from rdmo.projects.answers import AnswerTree

            answer_tree_factory = AnswerTree
        self.catalog = project.catalog
        self.catalog.prefetch_elements()
        values = project.values.filter(snapshot=None).select_related("attribute")
        self._answer_tree = _build_answer_tree(self.catalog, values, answer_tree_factory)
        self._scopes_by_key: dict[tuple[int, int, str, int], list[tuple[str, int]]] = {}

    def resolve(
        self,
        source_attribute_id: int,
        target_attribute_id: int,
        source_scope: tuple[str, int],
    ) -> list[tuple[str, int]]:
        key = (source_attribute_id, target_attribute_id, *source_scope)
        if key not in self._scopes_by_key:
            discovered_scopes = []
            for page in self.catalog.pages:
                if not _element_contains_attribute(page, source_attribute_id):
                    continue
                if not _element_contains_attribute(page, target_attribute_id):
                    continue
                for page_set in self._answer_tree.compute_element_sets(page, parent_set=None):
                    trigger_scopes = _collect_question_scopes(self._answer_tree, page, page_set, source_attribute_id)
                    if source_scope in trigger_scopes:
                        discovered_scopes.extend(_collect_question_scopes(self._answer_tree, page, page_set, target_attribute_id))
            self._scopes_by_key[key] = list(dict.fromkeys([*discovered_scopes, source_scope]))
        return list(self._scopes_by_key[key])


def _element_contains_attribute(element, attribute_id: int) -> bool:
    if getattr(element, "attribute_id", None) == attribute_id:
        return True
    return any(getattr(descendant, "attribute_id", None) == attribute_id for descendant in element.descendants)


def _collect_question_scopes(answer_tree, element, parent_set, attribute_id) -> list[tuple[str, int]]:
    scopes = []
    for child in element.elements:
        child_type = child._meta.model_name
        if child_type == "question":
            if child.attribute_id == attribute_id:
                scopes.append(parent_set)
        elif child_type == "questionset":
            for child_set in answer_tree.compute_element_sets(child, parent_set):
                scopes.extend(_collect_question_scopes(answer_tree, child, child_set, attribute_id))
    return scopes
