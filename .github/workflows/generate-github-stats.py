
import json
import os
import html
import urllib.request
import urllib.error

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


# ============================================================
# CONFIGURATION
# ============================================================

USERNAME = os.getenv("GITHUB_USERNAME", "kimvns")
TOKEN = os.getenv("GITHUB_TOKEN")

OUTPUT_DIR = Path(__file__).resolve().parent
GRAPHQL_URL = "https://api.github.com/graphql"

if not TOKEN:
    raise RuntimeError(
        "GITHUB_TOKEN não encontrado. "
        "Execute este script pelo GitHub Actions."
    )


# ============================================================
# GITHUB API
# ============================================================

def github_graphql(query, variables=None):
    payload = {
        "query": query,
        "variables": variables or {}
    }

    request = urllib.request.Request(
        GRAPHQL_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
            "Accept": "application/vnd.github+json"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))

    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"Erro HTTP {error.code} na API do GitHub: {details}"
        ) from error

    except urllib.error.URLError as error:
        raise RuntimeError(
            f"Falha de conexão com a API do GitHub: {error}"
        ) from error

    if result.get("errors"):
        raise RuntimeError(
            f"Erro GraphQL: {json.dumps(result['errors'], indent=2)}"
        )

    return result["data"]


# ============================================================
# CONTRIBUTION CALENDAR
# ============================================================

def fetch_contributions():
    query = """
    query($username: String!, $from: DateTime!, $to: DateTime!) {
      user(login: $username) {
        contributionsCollection(from: $from, to: $to) {
          contributionCalendar {
            totalContributions
            weeks {
              contributionDays {
                contributionCount
                date
                color
              }
            }
          }
        }
      }
    }
    """

    today = datetime.now(timezone.utc).date()
    start_date = today - timedelta(days=364)

    data = github_graphql(
        query,
        {
            "username": USERNAME,
            "from": f"{start_date.isoformat()}T00:00:00Z",
            "to": f"{today.isoformat()}T23:59:59Z"
        }
    )

    user = data.get("user")

    if not user:
        raise RuntimeError(f"Usuário GitHub não encontrado: {USERNAME}")

    calendar = user["contributionsCollection"]["contributionCalendar"]

    days = []

    for week in calendar["weeks"]:
        for day in week["contributionDays"]:
            days.append(day)

    if not days:
        raise RuntimeError("A API não retornou dias de contribuição.")

    return {
        "total": calendar["totalContributions"],
        "days": days,
        "start": start_date,
        "end": today
    }


# ============================================================
# PUBLIC REPOSITORIES
# ============================================================

def fetch_repositories():
    query = """
    query($username: String!, $cursor: String) {
      user(login: $username) {
        repositories(
          first: 100,
          after: $cursor,
          privacy: PUBLIC,
          ownerAffiliations: OWNER
        ) {
          totalCount
          nodes {
            stargazerCount
            primaryLanguage {
              name
              color
            }
          }
          pageInfo {
            hasNextPage
            endCursor
          }
        }
      }
    }
    """

    repositories = []
    cursor = None
    total_count = 0

    while True:
        data = github_graphql(
            query,
            {
                "username": USERNAME,
                "cursor": cursor
            }
        )

        user = data.get("user")

        if not user:
            raise RuntimeError(f"Usuário não encontrado: {USERNAME}")

        result = user["repositories"]

        total_count = result["totalCount"]
        repositories.extend(result["nodes"])

        page_info = result["pageInfo"]

        if not page_info["hasNextPage"]:
            break

        cursor = page_info["endCursor"]

    return {
        "total": total_count,
        "repositories": repositories
    }


# ============================================================
# SVG HELPERS
# ============================================================

def save_svg(filename, content):
    path = OUTPUT_DIR / filename
    path.write_text(content, encoding="utf-8")
    print(f"SVG gerado: {path}")


def svg_header(width, height, title):
    return f"""<svg xmlns="http://www.w3.org/2000/svg"
        width="{width}" height="{height}"
        viewBox="0 0 {width} {height}"
        role="img" aria-label="{html.escape(title)}">
    <title>{html.escape(title)}</title>
    <style>
        text {{
            font-family: -apple-system, BlinkMacSystemFont,
            'Segoe UI', sans-serif;
        }}
        .title {{
            fill: #e6edf3;
            font-size: 16px;
            font-weight: 600;
        }}
        .muted {{
            fill: #8b949e;
            font-size: 11px;
        }}
        .value {{
            fill: #e6edf3;
            font-size: 24px;
            font-weight: 700;
        }}
    </style>
"""


# ============================================================
# CONTRIBUTION CALENDAR SVG
# ============================================================

def generate_calendar_svg(calendar):
    days = calendar["days"]

    cell = 10
    gap = 3
    step = cell + gap

    left = 42
    top = 38

    weeks = defaultdict(dict)

    for day in days:
        date = datetime.strptime(day["date"], "%Y-%m-%d").date()

        # Python: Monday=0 ... Sunday=6
        # Calendar: Sunday=0 ... Saturday=6
        weekday = (date.weekday() + 1) % 7

        week_index = (date - calendar["start"]).days // 7

        weeks[week_index][weekday] = day

    total_weeks = max(weeks.keys()) + 1

    width = left + total_weeks * step + 15
    height = top + 7 * step + 30

    parts = [
        svg_header(width, height, "GitHub contribution calendar"),
        f'<text x="{left}" y="20" class="title">'
        f'{calendar["total"]:,} contribuições no período</text>'
    ]

    month_labels = {}
    for day in days:
        date = datetime.strptime(day["date"], "%Y-%m-%d").date()

        if date.day == 1 or date == calendar["start"]:
            week_index = (date - calendar["start"]).days // 7
            month_labels[week_index] = date.strftime("%b")

    for week_index, month in month_labels.items():
        x = left + week_index * step
        parts.append(
            f'<text x="{x}" y="34" class="muted">'
            f'{html.escape(month)}</text>'
        )

    weekdays = ["", "Mon", "", "Wed", "", "Fri", ""]

    for row, label in enumerate(weekdays):
        if label:
            y = top + row * step + 9
            parts.append(
                f'<text x="4" y="{y}" class="muted">{label}</text>'
            )

    for week_index in range(total_weeks):
        for weekday in range(7):
            day = weeks.get(week_index, {}).get(weekday)

            if not day:
                continue

            x = left + week_index * step
            y = top + weekday * step

            color = day.get("color") or "#161b22"

            if not (
                isinstance(color, str)
                and len(color) == 7
                and color.startswith("#")
            ):
                color = "#161b22"

            count = day["contributionCount"]
            date = day["date"]

            tooltip = html.escape(
                f"{count} contribuições em {date}",
                quote=True
            )

            parts.append(
                f'<rect x="{x}" y="{y}" '
                f'width="{cell}" height="{cell}" '
                f'rx="2" fill="{color}">'
                f'<title>{tooltip}</title></rect>'
            )

    parts.append("</svg>")

    save_svg(
        "contribution-calendar.svg",
        "\n".join(parts)
    )


# ============================================================
# MONTHLY CONTRIBUTIONS SVG
# ============================================================

def generate_monthly_svg(calendar):
    monthly = defaultdict(int)

    for day in calendar["days"]:
        date = datetime.strptime(day["date"], "%Y-%m-%d").date()
        key = date.strftime("%Y-%m")
        monthly[key] += day["contributionCount"]

    months = sorted(monthly.items())[-12:]

    width = 760
    height = 260

    left = 42
    top = 45
    chart_height = 155
    chart_width = 680

    max_value = max((value for _, value in months), default=0)
    max_value = max(max_value, 1)

    bar_width = 32
    spacing = chart_width / max(len(months), 1)

    parts = [
        svg_header(width, height, "Monthly GitHub contributions"),
        '<text x="20" y="25" class="title">'
        'Contribuições por mês</text>',
        f'<text x="20" y="42" class="muted">'
        f'Total no período: {calendar["total"]:,}</text>'
    ]

    parts.append(
        f'<line x1="{left}" y1="{top + chart_height}" '
        f'x2="{left + chart_width}" y2="{top + chart_height}" '
        f'stroke="#30363d"/>'
    )

    for index, (month, value) in enumerate(months):
        x = left + index * spacing + (spacing - bar_width) / 2

        bar_height = (value / max_value) * chart_height
        y = top + chart_height - bar_height

        parts.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" '
            f'width="{bar_width}" height="{bar_height:.1f}" '
            f'rx="4" fill="#2da44e">'
            f'<title>{value} contribuições em {month}</title>'
            f'</rect>'
        )

        parts.append(
            f'<text x="{x + bar_width / 2:.1f}" '
            f'y="{max(y - 7, top - 5):.1f}" '
            f'text-anchor="middle" class="muted">{value}</text>'
        )

        label = datetime.strptime(month, "%Y-%m").strftime("%b")

        parts.append(
            f'<text x="{x + bar_width / 2:.1f}" '
            f'y="{top + chart_height + 20}" '
            f'text-anchor="middle" class="muted">{label}</text>'
        )

    parts.append("</svg>")

    save_svg(
        "contributions-by-month.svg",
        "\n".join(parts)
    )


# ============================================================
# REPOSITORY STATISTICS SVG
# ============================================================

def generate_repository_svg(data):
    repositories = data["repositories"]

    total_repositories = data["total"]
    total_stars = sum(
        repo["stargazerCount"] for repo in repositories
    )

    languages = Counter()

    for repo in repositories:
        language = repo.get("primaryLanguage")

        if language and language.get("name"):
            languages[language["name"]] += 1

    top_languages = languages.most_common(5)

    width = 760
    height = 250

    parts = [
        svg_header(width, height, "Public GitHub repository statistics"),
        '<text x="24" y="28" class="title">'
        'Estatísticas dos repositórios públicos</text>'
    ]

    cards = [
        ("Repositórios públicos", total_repositories),
        ("Estrelas recebidas", total_stars)
    ]

    for index, (label, value) in enumerate(cards):
        x = 24 + index * 240

        parts.extend([
            f'<rect x="{x}" y="48" width="210" height="75" '
            'rx="8" fill="#161b22" stroke="#30363d"/>',
            f'<text x="{x + 16}" y="78" class="muted">'
            f'{label}</text>',
            f'<text x="{x + 16}" y="108" class="value">'
            f'{value:,}</text>'
        ])

    parts.append(
        '<text x="24" y="160" class="title">'
        'Linguagens principais por repositório</text>'
    )

    if not top_languages:
        parts.append(
            '<text x="24" y="190" class="muted">'
            'Nenhuma linguagem principal encontrada.</text>'
        )

    for index, (language, count) in enumerate(top_languages):
        y = 184 + index * 20

        parts.append(
            f'<text x="24" y="{y}" class="muted">'
            f'{html.escape(language)}</text>'
        )

        parts.append(
            f'<text x="320" y="{y}" class="muted">'
            f'{count} repositório(s)</text>'
        )

    parts.append("</svg>")

    save_svg(
        "repository-stats.svg",
        "\n".join(parts)
    )


# ============================================================
# MAIN
# ============================================================

def main():
    print(f"Consultando dados públicos de @{USERNAME}...")

    calendar = fetch_contributions()
    repositories = fetch_repositories()

    generate_calendar_svg(calendar)
    generate_monthly_svg(calendar)
    generate_repository_svg(repositories)

    print("\nGeração concluída!")
    print(f"Contribuições: {calendar['total']}")
    print(f"Repositórios públicos: {repositories['total']}")


if __name__ == "__main__":
    main()

