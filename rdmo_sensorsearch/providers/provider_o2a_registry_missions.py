import logging
from collections import defaultdict
from urllib.parse import quote

from rdmo_sensorsearch.client import fetch_json
from rdmo_sensorsearch.providers.base import BaseSensorProvider

logger = logging.getLogger(__name__)


class O2ARegistryMissionsProvider(BaseSensorProvider):
    """
    Searches the O2A Registry missions API and returns options for selection.
    """

    id_prefix = "o2amission"
    text_prefix = "O2A Mission"
    base_url = "https://registry.o2a-data.de/rest/v2/missions"

    query_url = "{base_url}?where={where}&sorts={sorts}&offset={offset}&hits={hits}"
    where_template = 'name=ILIKE="*{query}*"'
    sorts = ""
    offset = 0
    option_id = "{id_prefix}:{id}"
    option_text = "{prefix}({id}): {name}"

    def get_options(self, project, search=None, user=None, site=None):
        if search is None:
            return []

        query = self._sanitize_query(search)
        if not query:
            return []

        where = self.where_template.format(query=query)
        url = self.query_url.format(
            base_url=self.base_url,
            where=quote(where, safe='=*"'),
            sorts=quote(str(self.sorts)),
            offset=self.offset,
            hits=self.max_hits,
            query=quote(query),
        )
        json_data = fetch_json(url)

        records = json_data.get("records", []) if isinstance(json_data, dict) else []
        if not records:
            logger.debug("Empty response from O2A missions API for %s", search)
            return []

        return [
            {
                "id": self.option_id.format(id_prefix=self.id_prefix, id=mission.get("id", "")),
                "text": self._format_mission_text(mission),
            }
            for mission in records[:self.max_hits]
            if mission.get("id") is not None
        ]

    def _sanitize_query(self, search: str) -> str:
        return search.replace("\\", "\\\\").replace('"', '\\"').strip()

    def _format_mission_text(self, mission: dict) -> str:
        values = defaultdict(
            str,
            {
                "prefix": self.text_prefix,
                "id": mission.get("id", ""),
                "name": mission.get("name", ""),
                "description": mission.get("description") or "",
                "start_date": mission.get("startDate") or "",
                "end_date": mission.get("endDate") or "",
                "uuid": mission.get("@uuid") or "",
            },
        )
        return self.option_text.format_map(values)
