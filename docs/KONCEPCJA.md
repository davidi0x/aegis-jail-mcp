# Aegis Jail MCP

> Daj AI zadanie. Zachowaj kontrolę nad tym, do czego ma dostęp.

Aegis to (proponowana) aplikacja na Windows i macOS, która pozwala korzystać z agentów AI, dając im dostęp tylko do tego, czego potrzebują do pracy. Pomaga ustawić te granice, sprawdza je w praktyce i pilnuje ich podczas kolejnych zadań.

**Status:** koncept produktu — nie opis działającego systemu.

## 1. Problem

Użytkownik instaluje agenta, podpina projekt, terminal i kilka narzędzi MCP, ale nie wie:

- czy agent może przeczytać prywatne pliki i klucze,
- czy potrafi wysłać kod poza projekt,
- czy instalowany skill potrzebuje aż takich uprawnień,
- czy po aktualizacji dostęp agenta się rozszerzył,
- jak ograniczyć dostęp bez ciągłych błędów i pytań o zgodę.

Aegis zamienia „daję mu pełny dostęp, żeby działało” w „ma sprawdzony zakres dostępu do tego zadania”.

Pierwsi użytkownicy: programiści, osoby budujące aplikacje z AI, małe zespoły.

## 2. Darmowa funkcja: automatyczne zawężanie uprawnień z weryfikacją

Użytkownik wybiera projekt, obsługiwanego agenta i reprezentatywne zadanie. Aegis uruchamia je w przygotowanym środowisku, sprawdza wynik, a następnie próbuje wykonać je z mniejszym dostępem. Przykładowy wynik:

> Zadanie przeszło testy bez dostępu do kluczy SSH, pozostałych projektów i internetu po instalacji zależności. Zapisz ten profil dla kolejnych sesji.

Wyróżnik: połączenie ograniczenia uprawnień z dowodem, że praca nadal się udała. Wykrywanie dostępów i sandboxing już istnieją (np. Sandbox Probe, Anthropic Sandbox Runtime) — nie obiecujemy nowej kategorii. Wynik dotyczy konkretnych przetestowanych zadań, nie wszystkich możliwych.

## 3. W czym pomaga

| Sytuacja | Co robi Aegis | Korzyść |
|---|---|---|
| „Agent ma poprawić stronę” | Ogranicza pracę do projektu i niezbędnych narzędzi | Inne projekty i prywatne pliki poza zasięgiem |
| „Nie wiem, jakie uprawnienia ustawić” | Proponuje ograniczenia i testuje je na zadaniach | Mniej ręcznej konfiguracji |
| „W README jest złośliwa instrukcja” | Egzekwuje ograniczenia niezależnie od tego, co model przeczytał | Zmanipulowany agent nadal podlega polityce |
| „Agent chce skorzystać z nowej usługi” | Pokazuje zasób i operację wymagającą rozszerzenia | Świadoma decyzja użytkownika |
| „Agent coś zepsuł” | Pokazuje różnice z roboczej kopii projektu | Odrzucenie zmian przed przeniesieniem |
| „Po aktualizacji coś się zmieniło” | Ponownie testuje granice i porównuje wyniki | Widać regresję zabezpieczeń |
| „Chcę używać tego w zespole” | Wspólne, wersjonowane polityki | Powtarzalna konfiguracja i kontrola wyjątków |

Cofanie dotyczy plików w roboczej kopii. Wysłany e-mail, publikacja czy zmiana w zewnętrznej bazie nie są uniwersalnie odwracalne.

## 4. Przepływ użytkownika

**Pierwsze uruchomienie** — instalacja, wybór agenta i folderu projektu. Aegis pokazuje zakres ochrony i przygotowuje środowisko (bez ręcznej instalacji Linuksa).

**Przed zadaniem**

```
Projekt: sklep internetowy
Zapis: katalog projektu
Prywatne pliki i klucze: niedostępne
Sieć: wybrane usługi
Publikacja zmian: wymaga osobnej zgody
```

**Podczas pracy** — przy próbie przekroczenia granic: „Agent próbuje zapisać plik poza projektem. Dostęp został zablokowany.” Użytkownik odrzuca operację lub przyznaje wąski, czasowy wyjątek (nie wyłączenie ochrony).

**Po zadaniu** — zmienione pliki, wyniki niezależnych testów, zablokowane operacje, wykorzystane wyjątki; akceptacja zmian i opcjonalna optymalizacja uprawnień.

## 5. Warstwy („adaptacyjna Aegis”)

| Warstwa | Odpowiedzialność |
|---|---|
| Polityka zadania | Dozwolone pliki, narzędzia, zasoby i operacje |
| Izolacja wykonania | Egzekwowanie ograniczeń wobec agenta i procesów potomnych |
| Kontrola integracji | Ograniczanie operacji przez obsługiwane MCP i API |
| Weryfikacja | Sprawdzanie wyniku zadania i skuteczności ograniczeń |
| Adaptacja | Proponowanie, testowanie i zapisywanie ciaśniejszych polityk |

System może zatrzymać sesję po naruszeniu lub odebrać czasowy dostęp. Nigdy nie rozszerza uprawnień sam tylko dlatego, że agent poprosił. Nowe reguły są testowane przed szerszym zastosowaniem.

## 6. Windows i macOS

Wspólny interfejs i format polityk; osobne mechanizmy izolacji (Windows: m.in. AppContainer; macOS: natywny sandboxing). Pierwsze wydanie wspiera jednego agenta CLI na obu systemach, z opublikowaną listą wersji i testów. Edytory (np. Cursor) — dopiero po sprawdzeniu wszystkich dróg wykonywania operacji.

Ochrona obejmuje wyłącznie sesje uruchomione przez Hydrę.

## 7. Co jest darmowe (GitHub)

- Instalatory na Windows i macOS
- Uruchamianie obsługiwanego agenta w ograniczonym środowisku
- Profile dostępu dla projektów
- Testowanie ograniczeń i propozycje zmniejszenia uprawnień
- Lokalny raport z dowodami wykonanych prób
- Eksport polityk, dokumentacja, odtwarzalne demonstracje
- Brak obowiązkowego konta, telemetria domyślnie wyłączona

Powtórzenia zadań mogą zużywać płatne wywołania modelu użytkownika — aplikacja ma limity prób i budżetu.

Płatny produkt (dla zespołów): centralne zarządzanie, polityki organizacji, historia zmian, role administratorów, integracje, wsparcie.

## 8. Zakres pierwszego wydania

1. Chroniona sesja jednego agenta na Windows i macOS.
2. Kontrola plików i połączeń sieciowych, łącznie z procesami potomnymi.
3. Powtarzalny test zadania z ograniczonymi uprawnieniami.
4. Czytelny wynik i zapis sprawdzonego profilu.

Później: pośredniczenie w dostępie do sekretów, szczegółowe polityki MCP/API, panel organizacji.

**Przed premierą mierzymy:** czy ograniczenia działają, czy agent kończy zadania, ile pracy wymaga konfiguracja, ile kosztują powtórzenia. Najważniejszy sygnał: użytkownicy uruchamiający kolejne sesje z włączoną ochroną.
