"""Gera os CSVs sintéticos do OmniOps AI de forma reprodutível.

Reprodutibilidade (seção 12): semente fixa (`random.Random(SEED)`) e IDs
determinísticos (`uuid5`). Rodar duas vezes, em qualquer máquina, produz
arquivos idênticos byte a byte; o teste `test_generator_is_deterministic` cobra isso.

Cenários plantados (CLAUDE.md 6.2 e 8.2):

* LOTE-2026-DEF (100 unidades, 50 na linha L1 e 50 na L2):
  - 49 unidades distintas com defeito reclamado (taxa 49%); a 50ª será a de
    Mariana (ORD-20050), já reservada na L2, e virá pelo simulador de tráfego.
  - **Causa plantada:** 45 das 49 (≈92%) vêm da linha L2, sintoma "bateria estufada".
  - Duas reclamações da mesma unidade (devem contar uma).
  - Uma reclamação sem serial (fica fora do numerador).
  - **Distratores de taxa-base:** a transportadora RotaSul leva ~50% de todos os
    pedidos e uma semana de promoção concentra as vendas; ambas aparecem muito
    nas reclamações sem serem causa. Algumas mensagens citam atraso de entrega.
* LOTE-2026-SEP: lote anterior do mesmo produto e fábrica, saudável (~2%),
  para a comparação entre lotes mostrar que a L2 era boa em setembro.
"""

import csv
import random
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 42
# Namespace fixo para uuid5: mesmo nome -> mesmo UUID em qualquer máquina.
NAMESPACE = uuid.UUID("6f6d6e69-6f70-7300-8000-000000000000")
DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"

CARRIERS = ["RotaSul", "TransVale", "ExpressoNorte"]
CARRIER_WEIGHTS = [0.5, 0.3, 0.2]  # RotaSul domina o volume: distrator de taxa-base

L2_SYMPTOMS = [
    "Meu relógio está com a bateria estufada e a tampa traseira levantou.",
    "A bateria do relógio inchou e ele esquenta muito no pulso.",
    "O smartwatch parou de carregar e a parte de trás está estufada.",
    "Percebi a bateria estufada depois de uma semana de uso, a tela até descolou.",
    "O relógio ficou muito quente carregando e agora a bateria está estufada.",
]
L1_SYMPTOMS = [
    "A tela do relógio apareceu com pixels mortos no canto.",
    "A pulseira quebrou no fecho com poucos dias de uso.",
    "O botão lateral do relógio travou e não responde.",
    "A tela fica preta de vez em quando, mesmo com bateria.",
]
DELAY_REMARK = " Além disso, a entrega atrasou mais de uma semana."


def _uid(kind: str, key: str) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{kind}:{key}"))


def _ts(dt: datetime) -> str:
    """Datas sempre em UTC com fuso explícito (ISO 8601)."""
    return dt.astimezone(timezone.utc).isoformat()


def _utc(y: int, m: int, d: int, h: int = 12, mi: int = 0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc)


def _write(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _make_units(rng, batch_id, product_id, sigla, start, count, lines, made_on):
    """Cria `count` unidades com seriais sequenciais e linhas embaralhadas."""
    per_line = [lines[i % len(lines)] for i in range(count)]
    rng.shuffle(per_line)
    units = []
    for i in range(count):
        units.append({
            "serial_number": f"SN-{sigla}-{start + i:06d}",
            "batch_id": batch_id,
            "product_id": product_id,
            "order_id": "",
            "production_line": per_line[i],
            "manufactured_at": _ts(made_on - timedelta(hours=rng.randint(0, 71))),
        })
    return units


def _customer(cid, name, email, phone, tier="Regular", ltv="399.00", orders=1, rr=0.0):
    return {
        "customer_id": cid, "name": name, "email": email, "phone": phone, "tier": tier,
        "lifetime_value": ltv, "total_orders": orders, "return_rate": rr,
    }


def _order(oid, cid, pid, bid, value, status, carrier, purchased):
    return {
        "order_id": oid, "customer_id": cid, "product_id": pid, "batch_id": bid,
        "order_value": value, "carrier_status": status, "carrier": carrier,
        "purchase_date": _ts(purchased),
    }


def generate(data_dir: Path = DEFAULT_DATA_DIR) -> dict[str, int]:
    """Gera todos os CSVs em `data_dir` e devolve a contagem de linhas por arquivo."""
    data_dir.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)

    def carrier() -> str:
        return rng.choices(CARRIERS, CARRIER_WEIGHTS)[0]

    def def_purchase() -> datetime:
        # 4 semanas de venda; a semana 2 (promoção) concentra ~50%: distrator de taxa-base
        week = rng.choices([0, 1, 2, 3], [0.15, 0.5, 0.2, 0.15])[0]
        return _utc(2026, 10, 5) + timedelta(days=7 * week + rng.randint(0, 6), hours=rng.randint(8, 20))

    # ------------------------------------------------------------------ batches
    batches = [
        {"batch_id": "LOTE-2026-DEF", "product_id": "PROD-SMART-WATCH-X",
         "product_name": "Smartwatch Omni Pulse V2", "manufacturing_date": "2026-10-01",
         "factory_code": "FAC-SP-01", "total_units_produced": 100,
         "is_blocked": False, "proactive_recall_triggered": False},
        {"batch_id": "LOTE-2026-SEP", "product_id": "PROD-SMART-WATCH-X",
         "product_name": "Smartwatch Omni Pulse V2", "manufacturing_date": "2026-09-01",
         "factory_code": "FAC-SP-01", "total_units_produced": 100,
         "is_blocked": False, "proactive_recall_triggered": False},
        {"batch_id": "LOTE-2026-OK", "product_id": "PROD-EARBUDS-PRO",
         "product_name": "Fone de Ouvido Noise Cancel Pro", "manufacturing_date": "2026-09-15",
         "factory_code": "FAC-AM-02", "total_units_produced": 500,
         "is_blocked": False, "proactive_recall_triggered": False},
        {"batch_id": "LOTE-2026-BLOCKED", "product_id": "PROD-POWERBANK-MAX",
         "product_name": "Carregador Portátil 20000mAh Ultra", "manufacturing_date": "2026-08-10",
         "factory_code": "FAC-SC-03", "total_units_produced": 200,
         "is_blocked": True, "proactive_recall_triggered": True},
    ]

    # -------------------------------------------------------------------- units
    def_units = _make_units(rng, "LOTE-2026-DEF", "PROD-SMART-WATCH-X", "SW", 1, 100,
                            ["L1", "L2"], _utc(2026, 10, 1, 18))
    sep_units = _make_units(rng, "LOTE-2026-SEP", "PROD-SMART-WATCH-X", "SW", 101, 100,
                            ["L1", "L2"], _utc(2026, 9, 1, 18))
    ok_units = _make_units(rng, "LOTE-2026-OK", "PROD-EARBUDS-PRO", "EB", 1, 500,
                           ["L1", "L2"], _utc(2026, 9, 15, 18))
    pb_units = _make_units(rng, "LOTE-2026-BLOCKED", "PROD-POWERBANK-MAX", "PB", 1, 200,
                           ["L1", "L2"], _utc(2026, 8, 10, 18))

    def_l1 = [u for u in def_units if u["production_line"] == "L1"]
    def_l2 = [u for u in def_units if u["production_line"] == "L2"]
    rng.shuffle(def_l1)
    rng.shuffle(def_l2)
    # Reserva de unidades do lote DEF (L1: 50, L2: 50)
    defective = def_l2[:45] + def_l1[:4]   # 49 defeitos históricos: 45 L2 + 4 L1
    rng.shuffle(defective)
    mariana_unit = def_l2[45]               # a 50ª unidade defeituosa (L2)
    no_serial_unit = def_l2[46]             # unidade de quem reclama sem informar serial
    ok_pool = def_l1[4:] + def_l2[47:]      # 46 L1 + 3 L2 sem defeito reclamado
    rng.shuffle(ok_pool)

    # ---------------------------------------------------------------- customers
    customers = [
        _customer("a1111111-1111-1111-1111-111111111111", "Carlos Alberto VIP",
                  "carlos.vip@example.com", "+5511987654321", "VIP", "2500.00", 12, 0.04),
        _customer("b2222222-2222-2222-2222-222222222222", "Mariana Souza",
                  "mariana.souza@example.com", "+5511976543210", "Regular", "450.00", 2, 0.0),
        _customer("c3333333-3333-3333-3333-333333333333", "Lucas Silencioso",
                  "lucas.silva@example.com", "+5511912345678", "Regular", "320.00", 1, 0.0),
        _customer("d4444444-4444-4444-4444-444444444444", "Beatriz Silenciosa",
                  "beatriz.oliveira@example.com", "+5521998877665", "VIP", "1800.00", 6, 0.0),
        _customer("e5555555-5555-5555-5555-555555555555", "Fernanda Alergia",
                  "fernanda.alergia@example.com", "+5531988771122", "New", "89.00", 1, 0.0),
        _customer("f6666666-6666-6666-6666-666666666666", "Marcos Suspeito",
                  "marcos.suspeito@example.com", "+5541991122334", "New", "150.00", 3, 0.67),
        _customer(_uid("customer", "rafael"), "Rafael Sem Serial",
                  "rafael.sem.serial@example.com", "+5511955554444"),
    ]
    orders = [
        _order("ORD-10001", "a1111111-1111-1111-1111-111111111111", "PROD-EARBUDS-PRO",
               "LOTE-2026-OK", "89.90", "in_transit", "TransVale", _utc(2026, 11, 10, 14, 30)),
        _order("ORD-20050", "b2222222-2222-2222-2222-222222222222", "PROD-SMART-WATCH-X",
               "LOTE-2026-DEF", "349.90", "delivered_signed", "RotaSul", _utc(2026, 11, 5, 10, 15)),
        _order("ORD-20051", "c3333333-3333-3333-3333-333333333333", "PROD-SMART-WATCH-X",
               "LOTE-2026-DEF", "349.90", "delivered_signed", "TransVale", _utc(2026, 11, 6, 16, 45)),
        # Pedido com duas unidades (D6): a taxa conta unidades, não pedidos
        _order("ORD-20052", "d4444444-4444-4444-4444-444444444444", "PROD-SMART-WATCH-X",
               "LOTE-2026-DEF", "699.80", "delivered_signed", "RotaSul", _utc(2026, 11, 7, 11, 20)),
        _order("ORD-30001", "e5555555-5555-5555-5555-555555555555", "PROD-SMART-WATCH-X",
               "LOTE-2026-DEF", "349.90", "delivered_signed", "ExpressoNorte", _utc(2026, 11, 8, 9, 0)),
        _order("ORD-40001", "f6666666-6666-6666-6666-666666666666", "PROD-POWERBANK-MAX",
               "LOTE-2026-BLOCKED", "599.00", "delivered_signed", "RotaSul", _utc(2026, 11, 9, 18, 30)),
        _order("ORD-20053", _uid("customer", "rafael"), "PROD-SMART-WATCH-X",
               "LOTE-2026-DEF", "349.90", "delivered_signed", carrier(), def_purchase()),
    ]

    def assign(unit: dict, order_id: str) -> None:
        unit["order_id"] = order_id

    assign(mariana_unit, "ORD-20050")
    assign(ok_pool.pop(), "ORD-20051")
    assign(ok_pool.pop(), "ORD-20052")
    assign(ok_pool.pop(), "ORD-20052")
    assign(ok_pool.pop(), "ORD-30001")
    assign(no_serial_unit, "ORD-20053")
    assign(rng.choice(ok_units), "ORD-10001")
    assign(rng.choice(pb_units), "ORD-40001")

    # 49 consumidores históricos, cada um com uma unidade defeituosa
    for i, unit in enumerate(defective, start=1):
        cid = f"10000000-0000-0000-0000-{i:012d}"
        customers.append(_customer(cid, f"Consumidor Historico {i:02d}",
                                   f"historico{i:02d}@example.com", f"+551199000{i:04d}"))
        orders.append(_order(f"ORD-200{i:02d}", cid, "PROD-SMART-WATCH-X", "LOTE-2026-DEF",
                             "349.90", "delivered_signed", carrier(), def_purchase()))
        assign(unit, f"ORD-200{i:02d}")

    # 30 compradores silenciosos (sem reclamação): base de comparação para as taxas
    for i in range(1, 31):
        cid = _uid("customer", f"silent-{i:02d}")
        oid = f"ORD-2{i + 53:04d}"  # ORD-20054 .. ORD-20083
        status = "in_transit" if i <= 3 else ("delayed" if i <= 5 else "delivered_signed")
        customers.append(_customer(cid, f"Comprador Silencioso {i:02d}",
                                   f"silencioso{i:02d}@example.com", f"+5511981{i:06d}"))
        orders.append(_order(oid, cid, "PROD-SMART-WATCH-X", "LOTE-2026-DEF", "349.90",
                             status, carrier(), def_purchase()))
        assign(ok_pool.pop(), oid)

    # Lote anterior saudável: 2 compradores com defeito (1 por linha)
    sep_l1 = next(u for u in sep_units if u["production_line"] == "L1")
    sep_l2 = next(u for u in sep_units if u["production_line"] == "L2")
    sep_cases = [(1, sep_l1, L1_SYMPTOMS[1]), (2, sep_l2, L1_SYMPTOMS[0])]
    for i, unit, _ in sep_cases:
        cid = _uid("customer", f"sep-{i}")
        customers.append(_customer(cid, f"Cliente Lote Anterior {i:02d}",
                                   f"lote.anterior{i:02d}@example.com", f"+5511982{i:06d}"))
        orders.append(_order(f"ORD-2100{i}", cid, "PROD-SMART-WATCH-X", "LOTE-2026-SEP",
                             "349.90", "delivered_signed", carrier(), _utc(2026, 9, 10 + i)))
        assign(unit, f"ORD-2100{i}")

    # ------------------------------------------------------------------ tickets
    order_by_id = {o["order_id"]: o for o in orders}
    tickets = []

    def ticket(thread, cid, oid, serial, channel, text, created, health):
        tickets.append({
            "ticket_id": _uid("ticket", thread), "thread_id": thread, "customer_id": cid,
            "order_id": oid, "serial_number": serial or "", "channel": channel,
            "message_text": text, "intent": "defective_item",
            "sentiment_score": -0.85 if health else -0.6,
            "sentiment_label": "Extremamente Negativo" if health else "Negativo",
            "is_health_risk": health, "batch_flagged": False,
            "priority_score": 70 if health else 45,
            "autonomy_status": "escalated_specialist" if health else "human_in_the_loop",
            "created_at": _ts(created),
        })

    def complaint_date(oid: str) -> datetime:
        purchased = datetime.fromisoformat(order_by_id[oid]["purchase_date"])
        return purchased + timedelta(days=rng.randint(3, 12), hours=rng.randint(0, 10))

    for i, unit in enumerate(defective, start=1):
        oid = f"ORD-200{i:02d}"
        is_l2 = unit["production_line"] == "L2"
        text = rng.choice(L2_SYMPTOMS if is_l2 else L1_SYMPTOMS)
        if rng.random() < 0.25:
            text += DELAY_REMARK  # distrator textual: atraso não causa defeito
        text += f" Serial {unit['serial_number']}."
        channel = "email" if i % 2 == 0 else "whatsapp"
        ticket(f"hist-thread-{i:03d}", f"10000000-0000-0000-0000-{i:012d}", oid,
               unit["serial_number"], channel, text, complaint_date(oid), is_l2)

    # Mesma unidade reclamada de novo (outro canal): deve contar UMA unidade
    dup = tickets[6]
    ticket("hist-thread-dup-007", dup["customer_id"], dup["order_id"], dup["serial_number"],
           "reclame_aqui",
           "Já reclamei no WhatsApp e ninguém resolveu: a bateria continua estufada. "
           f"Serial {dup['serial_number']}.",
           datetime.fromisoformat(dup["created_at"]) + timedelta(days=4), True)

    # Reclamação sem serial: fica fora do numerador, contada à parte
    ticket("hist-thread-noserial-001", _uid("customer", "rafael"), "ORD-20053", None, "email",
           "Meu relógio novo está esquentando muito e a traseira parece inchada. "
           "Não encontrei o número de série na caixa.",
           complaint_date("ORD-20053"), True)

    for i, unit, text in sep_cases:
        ticket(f"hist-thread-sep-{i:03d}", _uid("customer", f"sep-{i}"), f"ORD-2100{i}",
               unit["serial_number"], "email", f"{text} Serial {unit['serial_number']}.",
               _utc(2026, 9, 20 + i), False)

    tickets.sort(key=lambda t: t["created_at"])
    units = def_units + sep_units + ok_units + pb_units

    files = {
        "batches.csv": batches, "customers.csv": customers, "orders.csv": orders,
        "units.csv": units, "historic_tickets.csv": tickets,
    }
    for name, rows in files.items():
        _write(data_dir / name, rows)
    return {name: len(rows) for name, rows in files.items()}


if __name__ == "__main__":
    for name, count in generate().items():
        print(f"{name}: {count} linhas")
