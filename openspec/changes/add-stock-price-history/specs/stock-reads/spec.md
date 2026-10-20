# Spec Delta

## Purpose

Read tools that describe a household's stock in Grocy; this capability starts with the
purchase price history of one product.

## ADDED Requirements

### Requirement: Product price history
The server SHALL provide a read tool `stock_price_history` at the `read` access level that
takes `product` (an existing id or an exact name) and returns that product's past purchase
prices from Grocy's `GET /stock/products/{productId}/price-history`, newest first, each with
its date, its price per stock unit and the store name (null when Grocy has none), together
with the product's stock unit. It SHALL send no write and no print request to Grocy.

#### Scenario: History by exact name
- **WHEN** a `read` token calls `stock_price_history` with the exact name of a product that
  was bought three times at different prices
- **THEN** the result lists three prices newest first, each with date, price and store, and
  names the product and its stock unit

#### Scenario: Purchase without a store
- **WHEN** one of the product's purchases was booked without a store
- **THEN** that price is listed with `store` null

#### Scenario: Partial name
- **WHEN** `stock_price_history` is called with part of a product's name
- **THEN** the call fails listing candidates, and the price history is not requested

### Requirement: Price summary over the whole history
The result SHALL include `lowest`, `highest` and `latest`, each with date, price and store,
computed over the product's whole history regardless of `limit` and `offset`; when several
purchases share the lowest or highest price, the most recent SHALL be reported. Purchases
without a price SHALL be listed but left out of the summary, and all three SHALL be null
when no purchase has a price.

#### Scenario: Summary on a later page
- **WHEN** `stock_price_history` is called with `limit` 1 and `offset` 1 for a product with
  three priced purchases
- **THEN** `prices` holds only the second-newest purchase, while `lowest`, `highest` and
  `latest` still reflect all three

#### Scenario: Same lowest price twice
- **WHEN** the product was bought at its lowest price at one store in September and at
  another store in October
- **THEN** `lowest` reports the October purchase and its store

#### Scenario: Never bought
- **WHEN** `stock_price_history` is called for a product with no purchases
- **THEN** `prices` is empty, `next_offset` is null and `lowest`, `highest` and `latest`
  are null

### Requirement: Price history pages
`stock_price_history` SHALL take `limit` (default 50, at most 200) and `offset`, SHALL
return `total` and `next_offset` (null on the last page), and its description SHALL state
the default page size and how to page with `next_offset`.

#### Scenario: Next page
- **WHEN** `stock_price_history` is called with `limit` 2 for a product with three priced
  purchases
- **THEN** two prices are returned, `total` is 3 and `next_offset` is 2
