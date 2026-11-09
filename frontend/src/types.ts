export interface Page<T> { items: T[]; total: number }
export interface Ref { id: number; code: string }
export interface ItemRef { id: number; sku: string; name: string }

export type Role = "ADMIN" | "SUPERVISOR" | "OPERATOR";
export interface User { id: number; username: string; full_name: string; email: string | null; role: Role; active: boolean }

export interface Meta {
  app_name: string; roles: Role[]; zone_types: string[]; location_types: string[]; inventory_statuses: string[];
  order_statuses: string[]; task_types: string[]; task_statuses: string[]; txn_types: string[];
  inbound_types: string[]; adjust_reasons: string[];
}

export interface Warehouse {
  id: number; code: string; name: string; address1: string | null; city: string | null; state: string | null;
  postal_code: string | null; country: string | null; active: boolean; shopify_location_id: string | null;
}
export interface Zone { id: number; warehouse_id: number; code: string; name: string; zone_type: string }
export interface Location {
  id: number; warehouse_id: number; zone_id: number | null; zone: Ref | null; code: string; aisle: string | null;
  bay: string | null; level: string | null; position: string | null; location_type: string; pickable: boolean;
  pick_sequence: number; max_units: number | null; active: boolean; units: number;
}
export interface Supplier { id: number; code: string; name: string; contact_name: string | null; email: string | null; phone: string | null; active: boolean }

export interface Item {
  id: number; sku: string; name: string; description: string | null; barcode: string | null; category: string | null;
  brand: string | null; supplier_id: number | null; uom: string; unit_cost: string | null; price: string | null;
  weight: string | null; weight_unit: string; length: string | null; width: string | null; height: string | null;
  dim_unit: string; reorder_point: number; reorder_qty: number; lot_tracked: boolean; default_location_id: number | null;
  default_location: Ref | null; image_url: string | null; active: boolean; shopify_product_id: string | null;
  shopify_variant_id: string | null; shopify_inventory_item_id: string | null; created_at: string; updated_at: string;
  on_hand: number; allocated: number; available: number;
}

export interface Balance {
  id: number; item: ItemRef; location: Ref; warehouse_id: number; zone_code: string | null; lot_number: string;
  expiration_date: string | null; status: string; qty_on_hand: number; qty_allocated: number; qty_available: number;
  updated_at: string;
}

export interface Txn {
  id: number; created_at: string; txn_type: string; item: ItemRef; from_location: Ref | null; to_location: Ref | null;
  lot_number: string; qty: number; from_status: string | null; to_status: string | null; reason_code: string | null;
  reference_type: string | null; reference_number: string | null; username: string | null; notes: string | null;
}

export interface InboundLine { id: number; line_no: number; item: ItemRef; qty_expected: number; qty_received: number }
export interface Inbound {
  id: number; number: string; order_type: string; status: string; warehouse_id: number;
  supplier: { id: number; code: string; name: string } | null; reference: string | null; expected_date: string | null;
  created_at: string; qty_expected: number; qty_received: number; notes?: string | null; closed_at?: string | null;
  lines?: InboundLine[];
}

export interface Allocation { id: number; location: Ref; lot_number: string; qty: number; qty_picked: number; status: string }
export interface OrderLine {
  id: number; line_no: number; item: ItemRef; external_line_id: string | null; qty_ordered: number;
  qty_allocated: number; qty_picked: number; qty_shipped: number; allocations: Allocation[];
}
export interface Shipment {
  id: number; number: string; status: string; carrier: string | null; service: string | null;
  tracking_number: string | null; packages: number; weight: string | null; packed_by: string | null;
  packed_at: string; shipped_at: string | null;
}
export interface Order {
  id: number; number: string; external_id: string | null; channel: string; status: string; priority: number;
  warehouse_id: number; wave: { id: number; number: string } | null; customer_name: string | null;
  ship_city: string | null; ship_state: string | null; ship_method: string | null; requested_ship_date: string | null;
  created_at: string; shipped_at: string | null; units: number; line_count: number;
  customer_email?: string | null; customer_phone?: string | null; ship_name?: string | null;
  ship_address1?: string | null; ship_address2?: string | null; ship_postal_code?: string | null;
  ship_country?: string | null; notes?: string | null; lines?: OrderLine[]; shipments?: Shipment[];
}

export interface Wave {
  id: number; number: string; warehouse_id: number; status: string; description: string | null; created_at: string;
  released_at: string | null; order_count: number; open_tasks: number; total_tasks: number;
}

export interface Task {
  id: number; task_type: string; status: string; priority: number; warehouse_id: number; item: ItemRef;
  lot_number: string; qty: number; qty_done: number; from_location: Ref | null; to_location: Ref | null;
  order_id: number | null; wave_id: number | null; reference_number: string | null; assigned_to: string | null;
  created_at: string; completed_at: string | null; completed_by: string | null;
}

export interface CountLine {
  id: number; location: Ref; item: ItemRef; lot_number: string; inv_status: string; expected_qty: number | null;
  counted_qty: number | null; adjusted_qty: number | null; counted_by: string | null;
}
export interface Count {
  id: number; number: string; warehouse_id: number; status: string; description: string | null; blind: boolean;
  created_by: string | null; created_at: string; completed_at: string | null; line_count: number;
  counted_lines: number; lines?: CountLine[];
}
