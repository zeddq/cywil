#!/usr/bin/env python3
"""
Test script to demonstrate the corrected Polish legal document hierarchy
"""

from pdf2chunks import PolishStatuteParser

def test_hierarchy_parsing():
    """Test the hierarchy parsing with sample text"""
    
    # Sample text with proper Polish legal structure
    sample_kc_text = """USTAWA
z dnia 23 kwietnia 1964 r.
Kodeks cywilny

CZĘŚĆ OGÓLNA

DZIAŁ I
PRZEPISY WSTĘPNE

Art. 1. Kodeks niniejszy reguluje stosunki cywilnoprawne między osobami fizycznymi i osobami prawnymi.

Art. 2. Przepisy innych ustaw regulujące stosunki cywilnoprawne stosuje się, jeżeli przepisy te nie są sprzeczne z zasadami prawa cywilnego.

DZIAŁ II
OSOBY

Rozdział I
Osoby fizyczne

Art. 8. § 1. Każdy człowiek od chwili urodzenia ma zdolność prawną.
§ 2. Zdolność prawną mają także osoby prawne oraz jednostki organizacyjne niebędące osobami prawnymi, którym ustawa przyznaje zdolność prawną.

Art. 9. Pełną zdolność do czynności prawnych nabywa się z chwilą uzyskania pełnoletności.

Rozdział II
Osoby prawne

Art. 33. Osobami prawnymi są Skarb Państwa i jednostki organizacyjne, którym przepisy szczególne przyznają osobowość prawną.

CZĘŚĆ SZCZEGÓLNA

KSIĘGA PIERWSZA

DZIAŁ I
CZYNNOŚCI PRAWNE

Rozdział I
Przepisy ogólne

Art. 56. Czynność prawna wywołuje nie tylko skutki w niej wyrażone, lecz również te, które wynikają z ustawy, z zasad współżycia społecznego i z ustalonych zwyczajów."""
    
    sample_kpc_text = """
    USTAWA
    z dnia 17 listopada 1964 r.
    Kodeks postępowania cywilnego
    
    CZĘŚĆ PIERWSZA
    POSTĘPOWANIE ROZPOZNAWCZE
    
    KSIĘGA PIERWSZA
    PROCES
    
    TYTUŁ I
    PRZEPISY OGÓLNE
    
    DZIAŁ I
    SĄD
    
    Rozdział I
    Właściwość sądów
    
    Art. 1. Kodeks postępowania cywilnego normuje postępowanie sądowe w sprawach ze stosunków z zakresu prawa cywilnego, rodzinnego i opiekuńczego oraz prawa pracy, jak również w sprawach z zakresu ubezpieczeń społecznych oraz w innych sprawach, do których przepisy tego Kodeksu stosuje się z mocy ustaw szczególnych.
    
    Art. 2. § 1. Do rozpoznawania spraw cywilnych powołane są sądy powszechne, o ile sprawy te nie należą do właściwości sądów szczególnych, oraz Sąd Najwyższy.
    § 2. Sądy powszechne rozpoznają również sprawy z zakresu prawa pracy i ubezpieczeń społecznych.
    
    TYTUŁ VI
    POSTĘPOWANIE
    
    DZIAŁ I
    PRZEBIEG POSTĘPOWANIA
    
    Rozdział I
    Pisma procesowe
    
    Art. 126. § 1. Każde pismo procesowe powinno zawierać:
    1) oznaczenie sądu, do którego jest skierowane, imię i nazwisko lub nazwę stron, ich przedstawicieli ustawowych i pełnomocników;
    2) oznaczenie rodzaju pisma;
    3) osnowę wniosku lub oświadczenia oraz dowody na poparcie przytoczonych okoliczności;
    4) podpis strony albo jej przedstawiciela ustawowego lub pełnomocnika;
    5) wymienienie załączników.
    """
    
    print("=== Testing Polish Legal Document Hierarchy Parser ===\n")
    
    # Test KC parsing
    print("1. Testing Kodeks Cywilny (KC) Structure:")
    print("-" * 50)
    
    kc_parser = PolishStatuteParser("KC")
    kc_articles = kc_parser._parse_text(sample_kc_text)
    
    for article in kc_articles:
        print(f"\nArticle: {article.article_num}")
        print(f"Section Path: {article.section}")
        hierarchy = article.metadata.get('hierarchy', {})
        if hierarchy:
            print(f"Hierarchy Details:")
            if hierarchy.get('part'):
                print(f"  - Part: {hierarchy['part']}")
            if hierarchy.get('division'):
                print(f"  - Division: {hierarchy['division']}")
            if hierarchy.get('chapter'):
                print(f"  - Chapter: {hierarchy['chapter']}")
            if hierarchy.get('book'):
                print(f"  - Book: {hierarchy['book']}")
        print(f"Content: {article.content[:100]}...")
    
    # Test KPC parsing
    print("\n\n2. Testing Kodeks Postępowania Cywilnego (KPC) Structure:")
    print("-" * 50)
    
    kpc_parser = PolishStatuteParser("KPC")
    kpc_articles = kpc_parser._parse_text(sample_kpc_text)
    
    for article in kpc_articles:
        print(f"\nArticle: {article.article_num}")
        print(f"Section Path: {article.section}")
        hierarchy = article.metadata.get('hierarchy', {})
        if hierarchy:
            print(f"Hierarchy Details:")
            if hierarchy.get('part'):
                print(f"  - Part: {hierarchy['part']}")
            if hierarchy.get('book'):
                print(f"  - Book: {hierarchy['book']}")
            if hierarchy.get('title'):
                print(f"  - Title: {hierarchy['title']}")
            if hierarchy.get('division'):
                print(f"  - Division: {hierarchy['division']}")
            if hierarchy.get('chapter'):
                print(f"  - Chapter: {hierarchy['chapter']}")
        print(f"Content: {article.content[:100]}...")
    
    # Summary
    print("\n\n=== Summary ===")
    print(f"KC Articles parsed: {len(kc_articles)}")
    print(f"KPC Articles parsed: {len(kpc_articles)}")
    print("\nHierarchy Levels Found:")
    print("- KC: Część → Dział → Rozdział → Artykuł")
    print("- KPC: Część → Księga → Tytuł → Dział → Rozdział → Artykuł")

if __name__ == "__main__":
    test_hierarchy_parsing()