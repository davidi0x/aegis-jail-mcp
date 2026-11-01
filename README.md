# Hydra

> Daj AI zadanie. Zachowaj kontrolę nad tym, do czego ma dostęp.

Hydra uruchamia agenta AI (pierwszy obsługiwany: **Claude Code**) w izolowanej sesji, w której agent ma dostęp tylko do tego, czego potrzebuje. Potem **sprawdza w praktyce**, że te granice działają, i **automatycznie zawęża uprawnienia**, za każdym razem dowodząc, że zadanie nadal przechodzi testy.

```
$ hydra optimize
[hydra] run 1/12: baseline: PASS
[hydra] run 2/12: without home-read: PASS
[hydra] run 3/12: without secret:ssh, secret:aws: PASS
[hydra] run 4/12: without net-task-any: PASS
...
The task passed its tests without: reading the rest of the home directory; access to ~/.ssh (credentials);
access to ~/.aws (credentials); internet after dependency installation.
Saved verified profile to .hydra/profiles/verified.json
```

Status: **wersja 0.1, wczesna**. Działa na Linuksie (bubblewrap) i macOS (Seatbelt). Backend Windows (AppContainer) jest zaimplementowany i testowany w CI; traktuj go jako eksperymentalny. Pełny koncept produktu: [docs/KONCEPCJA.md](docs/KONCEPCJA.md).

## Co jest w tej wersji

| Funkcja | Komenda |
|---|---|
| Chroniona sesja agenta: robocza kopia projektu, blokada plików, sieci i zmiennych środowiskowych, obejmująca procesy potomne | `hydra run` |
| Testy granic: próby odczytu sekretów, zapisu poza projekt i połączeń sieciowych, porównywane z polityką | `hydra probe [--compare]` |
| Automatyczne zawężanie uprawnień z ponownym uruchamianiem zadania, limit prób i czasu | `hydra optimize` |
| Zapis sprawdzonego profilu z dowodami (które przebiegi, co usunięto) | `.hydra/profiles/*.json` |
| Przegląd zmian i świadoma decyzja: zastosuj albo odrzuć | `hydra diff`, `hydra apply`, `hydra discard` |
| Lokalny raport z każdej sesji: fazy, zmienione pliki, zablokowane operacje, użyte wyjątki | `hydra show` |
| Wąskie, czasowe wyjątki sieciowe (tylko na tę sesję) zamiast wyłączania ochrony | `hydra run --ask` |
| Eksport i współdzielenie polityk (pliki JSON w repo projektu) | `hydra profile export` |

Bez konta i bez telemetrii. Wszystko działa lokalnie.

## Instalacja

Wymagany jest Python 3.10+. Hydra nie ma zależności poza biblioteką standardową.

**macOS / Linux**

```sh
curl -fsSL https://raw.githubusercontent.com/IwanskyDD/Hydra/main/scripts/install.sh | sh
```

Na Linuksie potrzebny jest też `bubblewrap` (`sudo apt install bubblewrap`).

**Windows (PowerShell)**

```powershell
irm https://raw.githubusercontent.com/IwanskyDD/Hydra/main/scripts/install.ps1 | iex
```

**Z kodu**

```sh
git clone https://github.com/IwanskyDD/Hydra && cd Hydra && python3 -m pip install .
```

Sprawdź, czy sandbox działa na Twoim komputerze:

```sh
hydra doctor
```

## Demo w 1 minutę (bez kosztów modelu)

`examples/demo-project` to mały projekt z błędem i "agentem" w formie skryptu, który zachowuje się jak zmanipulowany model. W README projektu ukryto złośliwą instrukcję, więc agent próbuje przeczytać `~/.ssh` i `~/.aws`, wysłać je do `collector.evil.example` i zapisać plik w katalogu domowym. Dopiero potem naprawia błąd.

```sh
cd examples/demo-project
hydra probe        # 13/13 granic działa
hydra run          # agent naprawia błąd; kradzież kluczy, wysyłka i zapis poza projekt są zablokowane
hydra diff         # przegląd zmian z roboczej kopii
hydra apply        # albo: hydra discard
hydra optimize     # od szerokich uprawnień do minimalnych, z dowodem, że testy przechodzą
```

Na Windowsie zamień w `.hydra/task.json` `python3` na `python`.

## Użycie z Claude Code

```sh
cd moj-projekt
hydra init                       # tworzy .hydra/profiles/default.json i .hydra/task.json
# wpisz w .hydra/task.json reprezentatywne zadanie:
#   "prompt": "Popraw walidację formularza w src/form.ts",
#   "setup":  "npm ci",
#   "verify": "npm test"
hydra probe                      # czy granice trzymają
hydra run                        # zadanie w chronionej sesji
hydra optimize --max-runs 8      # znajdź minimalny, sprawdzony profil (każda próba = wywołania modelu!)
hydra run --profile verified     # kolejne sesje ze sprawdzonym profilem
```

W sesji Hydry Claude Code działa z `--dangerously-skip-permissions`. Agent nie pyta o zgodę na każde polecenie, ale granice egzekwuje system operacyjny, a nie model. Złośliwa instrukcja w README niczego nie zmienia.

## Jak to działa

```
projekt ──kopia──► robocza kopia ──► [setup] ──► [agent] ──► [verify] ──► raport ──► hydra apply / discard
                                         │           │           │
                                         └── sandbox systemu operacyjnego (+ procesy potomne)
                                              pliki: tylko robocza kopia do zapisu, dom i sekrety ukryte
                                              sieć:  brak / tylko lista domen przez proxy Hydry / pełna
                                              env:   tylko bezpieczne zmienne + jawnie przyznane
```

**Profil** to lista uprawnień nałożonych na bazę, która domyślnie wszystko blokuje:

- katalog domowy jest nieczytelny, a magazyny poświadczeń (`~/.ssh`, `~/.aws`, `~/.gnupg`, `~/.kube`, `~/.netrc`…) pozostają zablokowane nawet przy szerszym uprawnieniu, dopóki nie zostaną przyznane jawnie;
- oryginalny katalog projektu jest niewidoczny, bo agent pracuje na kopii;
- zapis jest możliwy tylko w roboczej kopii i prywatnym katalogu tymczasowym;
- sieć jest wyłączona; uprawnienia sieciowe dotyczą fazy `setup` (instalacja zależności) albo `task` (praca agenta);
- zmienne środowiskowe nie są dziedziczone poza bezpiecznym zestawem.

```json
{
  "hydra": 1,
  "name": "default",
  "agent": "claude-code",
  "grants": [
    { "id": "net-setup-any", "kind": "net", "domains": ["*"], "phase": "setup" },
    { "id": "docs", "kind": "net", "domains": ["*.python.org"], "phase": "task" },
    { "id": "shared-lib", "kind": "read", "path": "~/code/shared-lib" }
  ]
}
```

Rodzaje uprawnień: `read` / `write` (ścieżka), `net` (domeny; `*.x.com` lub `*`), `env` (nazwy zmiennych). `locked: true` oznacza uprawnienie wymagane przez agenta, którego `optimize` nie usuwa.

**Izolacja w poszczególnych systemach**

| | Pliki | Sieć | Procesy potomne |
|---|---|---|---|
| Linux | bubblewrap: system tylko do odczytu, ukryte katalogi jako puste tmpfs (tylko do odczytu) | osobna przestrzeń nazw sieci; jedyne wyjście to most do proxy Hydry | dziedziczą przestrzenie nazw |
| macOS | profil Seatbelt (`sandbox-exec`), generowany na każdą sesję | `deny network-outbound` poza portem proxy | dziedziczą sandbox |
| Windows | AppContainer + ACE na przyznanych ścieżkach (sprzątane po sesji) | brak uprawnień sieciowych albo `internetClient`; lista domen wymaga wyjątku loopback (uprawnienia administratora) | AppContainer + Job Object |

**Testy granic** (`hydra probe`) uruchamiają w sandboxie program, a w nim proces potomny, który próbuje: przeczytać plik-kanarek z sekretem, poświadczenia, oryginalny projekt i inne pliki domowe; zapisać plik w domu, w stanie Hydry i w oryginalnym projekcie; połączyć się z internetem bezpośrednio i przez proxy. Zapisy weryfikuje host, odczyty są porównywane z odciskiem prawdziwej zawartości, a test sieci ma próbę kontrolną. Jeśli komputer jest offline, wynik brzmi „inconclusive”, a nie fałszywe „pass”. `--compare` pokazuje regresje względem poprzedniego testu, np. po aktualizacji agenta.

**Optymalizacja** (`hydra optimize`) zaczyna od szerokiego profilu (dom, poświadczenia, internet, zmienne z tokenami) albo od wskazanego (`--start`). Usuwa grupy uprawnień, a gdy grupa okazuje się potrzebna, pojedyncze uprawnienia. Każda próba to świeża robocza kopia, setup, agent i niezależny `verify`. Na koniec wykonuje przebieg potwierdzający. Limity `--max-runs` i `--max-minutes` chronią budżet na wywołania modelu.

## Ograniczenia (uczciwie)

- **Wynik dotyczy przetestowanych zadań.** Jedna udana próba nie dowodzi, że profil wystarczy do wszystkiego. Agenci są niedeterministyczni, dlatego warto używać `--confirm 2` lub więcej.
- **Pierwsza próba `optimize` od profilu bazowego ma szeroki dostęp** (mniej więcej taki, jaki agent dostaje bez Hydry). Zapis i tak jest ograniczony do kopii. Jeśli chcesz tego uniknąć, użyj `--start <profil>`.
- Ochrona obejmuje **tylko sesje uruchomione przez Hydrę**, a nie każdego agenta na komputerze.
- Lista domen działa dla programów, które respektują `HTTPS_PROXY`. Pozostałe połączenia są blokowane, a nie przepuszczane.
- macOS: Seatbelt w Hydrze ogranicza pliki i sieć, ale nie inne mechanizmy IPC (np. usługi Mach). `sandbox-exec` jest oznaczony przez Apple jako przestarzały, choć nadal działa i korzystają z niego inne narzędzia.
- Windows: listy domen wymagają uprawnień administratora (wyjątek loopback). Bez tego Hydra odmawia, zamiast poszerzać dostęp. Backend jest nowy i wymaga testów z prawdziwymi agentami.
- Wykrywanie zablokowanych operacji plikowych w raporcie jest heurystyczne (na podstawie komunikatów błędów). Operacje sieciowe są logowane dokładnie przez proxy.
- Cofanie zmian dotyczy plików w roboczej kopii. Operacji zewnętrznych (e-mail, publikacja, zmiany w bazie) nie da się w ten sposób odwrócić.

## Rozwój

```sh
python3 -m unittest discover -s tests -t . -v                         # testy jednostkowe i z prawdziwym sandboxem
HYDRA_REQUIRE_SANDBOX=1 python3 -m unittest discover -s tests -t .    # niech brak sandboxa = błąd
```

CI uruchamia testy na Ubuntu, macOS i Windows ([.github/workflows/ci.yml](.github/workflows/ci.yml)).

Plan po 0.1 (zgodnie z [koncepcją](docs/KONCEPCJA.md)): aplikacja okienkowa i podpisane instalatory, pośredniczenie w dostępie do sekretów, szczegółowe polityki MCP/API, interaktywne wyjątki plikowe, polityki zespołowe i panel organizacji.
