# Aegis (po polsku)

**Daj AI zadanie, a nie cały komputer.** Aegis to sandbox dla agentów AI i serwerów MCP. Agent nie widzi katalogu domowego, kluczy ani sieci, dopóki nie sprawdzisz, że zadanie naprawdę tego potrzebuje.

Pełna dokumentacja (po angielsku): [README.md](README.md). Koncepcja produktu: [docs/KONCEPCJA.md](docs/KONCEPCJA.md).

## Szybki start

```sh
pip install git+https://github.com/IwanskyDD/aegis-mcp-jail
aegis demo
```

Na Linuksie najpierw zainstaluj `bubblewrap`. Demo pokazuje agenta zmanipulowanego przez złośliwą instrukcję w README. Agent próbuje ukraść `~/.ssh` i `~/.aws` i wysłać je na zewnątrz, ale Aegis to blokuje, a błąd w projekcie i tak zostaje naprawiony.

## Najważniejsze komendy

| Komenda | Co robi |
|---|---|
| `aegis run --agent claude-code --prompt "..." --verify "npm test"` | Zadanie w chronionej sesji na kopii projektu |
| `aegis diff` / `aegis apply` / `aegis discard` | Przegląd zmian i decyzja |
| `aegis optimize` | Szuka minimalnych uprawnień: zaczyna od zera, uczy się potrzebnych hostów, usuwa zbędne uprawnienia i zapisuje sprawdzony profil |
| `aegis probe [--compare]` | Sprawdza w praktyce, czy granice trzymają (także po aktualizacjach) |
| `aegis mcp-jail -- <serwer MCP>` | Uruchamia dowolny serwer MCP w sandboxie, z zaporą narzędzi i logiem audytu |
| `aegis mcp-server` | Udostępnia narzędzia Aegis klientom MCP (Claude Code, Claude Desktop, Cursor) |
| `aegis wrap -- <polecenie>` | Dowolne polecenie interaktywnie w sandboxie |

## Plugin do Claude Code

```
/plugin marketplace add IwanskyDD/aegis-mcp-jail
/plugin install aegis@aegis
```

Plugin dodaje serwer MCP z narzędziami sandboxa, hook blokujący dostęp do poświadczeń (`~/.ssh`, `~/.aws`…) oraz komendy `/aegis:sandbox`, `/aegis:probe` i `/aegis:audit`.

## Ochrona w poszczególnych systemach

Linux: bubblewrap. macOS: Seatbelt. Windows: AppContainer. CI uruchamia wszystkie testy sandboxa na wszystkich trzech systemach.
