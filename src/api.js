import { supabase } from './supabase'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || (import.meta.env.PROD ? '' : 'http://localhost:8000')
const useSupabaseAuth = Boolean(supabase) && !API_BASE_URL.includes('localhost')
const OFFLINE_QUEUE_KEY = 'vahana:offline-mutations'
function mapVehicle(vehicle) {
  return {
    ...vehicle,
    reg: vehicle.registration_number,
    km: `${vehicle.odometer_km.toLocaleString()} km`,
    driver: vehicle.driver_name || 'Unassigned',
    accent: vehicle.status === 'In workshop' ? 'orange' : vehicle.status === 'On route' ? 'blue' : 'green',
  }
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
  })

  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const error = new Error(body?.detail || `Request failed with status ${response.status}`)
    error.status = response.status
    throw error
  }

  return response.json()
}

function queueOfflineMutation(path, token, payload) {
  const queue = JSON.parse(localStorage.getItem(OFFLINE_QUEUE_KEY) || '[]')
  queue.push({
    id: crypto.randomUUID(),
    path,
    token,
    payload,
    idempotencyKey: crypto.randomUUID(),
  })
  localStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(queue))
}

export async function flushOfflineMutations() {
  const queue = JSON.parse(localStorage.getItem(OFFLINE_QUEUE_KEY) || '[]')
  const remaining = []
  for (const item of queue) {
    try {
      await request(item.path, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${item.token}`,
          'Idempotency-Key': item.idempotencyKey,
        },
        body: JSON.stringify(item.payload),
      })
    } catch (error) {
      if (error.status !== 409) remaining.push(item)
    }
  }
  localStorage.setItem(OFFLINE_QUEUE_KEY, JSON.stringify(remaining))
  return { flushed: queue.length - remaining.length, pending: remaining.length }
}

export async function login(email, password) {
  if (useSupabaseAuth) {
    const { data, error } = await supabase.auth.signInWithPassword({ email, password })
    if (!error && data.session) {
      return { access_token: data.session.access_token, token_type: 'bearer' }
    }
    throw new Error(error?.message || 'Unable to sign in')
  }
  return request('/api/v1/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}

export async function requestPasswordReset(email) {
  if (!useSupabaseAuth) {
    throw new Error('Password recovery is available through the configured Supabase Auth provider.')
  }
  const { error } = await supabase.auth.resetPasswordForEmail(email, {
    redirectTo: `${window.location.origin}/?page=app&reset=1`,
  })
  if (error) throw new Error(error.message)
}

export async function updatePassword(password) {
  if (!useSupabaseAuth) {
    throw new Error('Password recovery is available through the configured Supabase Auth provider.')
  }
  const { error } = await supabase.auth.updateUser({ password })
  if (error) throw new Error(error.message)
}

export async function logout() {
  if (useSupabaseAuth) {
    const { error } = await supabase.auth.signOut()
    if (error) throw new Error(error.message)
  }
}

export function signupOrganization(payload) {
  return request('/api/v1/auth/signup', {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(async (result) => {
    if (useSupabaseAuth) {
      return login(payload.email, payload.password)
    }
    return result
  })
}

export function acceptInvitation(payload) {
  return request('/api/v1/auth/invitations/accept', {
    method: 'POST',
    body: JSON.stringify(payload),
  }).then(async (result) => {
    if (useSupabaseAuth) {
      return login(result.user.email, payload.password)
    }
    return result
  })
}

export function createInvitation(token, payload) {
  return request('/api/v1/invitations', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  })
}

export function getInvitations(token) {
  return request('/api/v1/invitations', { headers: { Authorization: `Bearer ${token}` } })
}

export function revokeInvitation(token, invitationId) {
  return request(`/api/v1/invitations/${invitationId}/revoke`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
}

export function getUsers(token) {
  return request('/api/v1/users', { headers: { Authorization: `Bearer ${token}` } })
}

export function createUser(token, payload) {
  return request('/api/v1/users', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  })
}

export function updateUserRole(token, userId, role) {
  return request(`/api/v1/users/${userId}`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ role }),
  })
}

export function getVehicles(token) {
  return request('/api/v1/vehicles', {
    headers: { Authorization: `Bearer ${token}` },
  }).then((vehicles) => vehicles.map(mapVehicle))
}

export function updateVehicle(token, vehicleId, payload) {
  return request(`/api/v1/vehicles/${vehicleId}`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  }).then(mapVehicle)
}

export function getCurrentUser(token) {
  return request('/api/v1/auth/me', { headers: { Authorization: `Bearer ${token}` } })
}

export function getAuditLog(token, filters = {}) {
  const params = new URLSearchParams(Object.entries(filters).filter(([, value]) => value !== undefined && value !== ''))
  return request(`/api/v1/audit-log${params.toString() ? `?${params}` : ''}`, { headers: { Authorization: `Bearer ${token}` } })
}

export function getFleetOperationsSummary(token) {
  return request('/api/v1/fleet/operations-summary', { headers: { Authorization: `Bearer ${token}` } })
}

export function getFleetAnalytics(token) {
  return request('/api/v1/fleet/analytics', { headers: { Authorization: `Bearer ${token}` } })
}

export function updateMyContact(token, mobile_phone) {
  return request('/api/v1/users/me/contact', {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ mobile_phone }),
  })
}

export function updateMyProfile(token, profile) {
  return request('/api/v1/users/me', {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(profile),
  })
}

export function getSubscription(token) {
  return request('/api/v1/subscription', { headers: { Authorization: `Bearer ${token}` } })
}

export function changeSubscription(token, planCode) {
  return request('/api/v1/subscription', {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ plan_code: planCode }),
  })
}

export function getSubscriptionPlans(token) {
  return request('/api/v1/subscription/plans', { headers: { Authorization: `Bearer ${token}` } })
}

export function createSubscriptionCheckout(token, planCode) {
  return request('/api/v1/subscription/checkout', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ plan_code: planCode }),
  })
}

export function verifySubscriptionPayment(token, payment) {
  return request('/api/v1/subscription/verify', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(payment),
  })
}

export function getNotificationPreferences(token) {
  return request('/api/v1/notification-preferences', { headers: { Authorization: `Bearer ${token}` } })
}

export function updateNotificationPreference(token, preference) {
  return request('/api/v1/notification-preferences', {
    method: 'PUT',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(preference),
  })
}

export function getNotificationDeliveries(token) {
  return request('/api/v1/notification-deliveries', { headers: { Authorization: `Bearer ${token}` } })
}

export function dispatchQueuedSms(token) {
  return request('/api/v1/notification-deliveries/dispatch', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
}

export function createVehicle(token, vehicle) {
  return request('/api/v1/vehicles', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({
      registration_number: vehicle.reg,
      model: vehicle.model,
      vehicle_type: vehicle.type,
      depot: vehicle.depot,
      status: 'Idle / parked',
      health: 100,
      odometer_km: 0,
      driver_name: null,
    }),
  }).then(mapVehicle)
}

export function getWorkOrders(token) {
  return request('/api/v1/work-orders', { headers: { Authorization: `Bearer ${token}` } })
}

export function getVehicleAssignments(token, vehicleId) {
  return request(`/api/v1/vehicles/${vehicleId}/assignments`, { headers: { Authorization: `Bearer ${token}` } })
}

export function getVehicleOdometer(token, vehicleId) {
  return request(`/api/v1/vehicles/${vehicleId}/odometer`, { headers: { Authorization: `Bearer ${token}` } })
}

export function getBillingInvoices(token) {
  return request('/api/v1/billing/invoices', { headers: { Authorization: `Bearer ${token}` } })
}

export function getBillingPayments(token, invoiceId) {
  return request(`/api/v1/billing/invoices/${invoiceId}/payments`, { headers: { Authorization: `Bearer ${token}` } })
}

export function createWorkOrder(token, workOrder) {
  return request('/api/v1/work-orders', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(workOrder),
  })
}

export function updateWorkOrder(token, workOrderId, payload) {
  return request(`/api/v1/work-orders/${workOrderId}`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  })
}

export function getComponents(token) {
  return request('/api/v1/components', { headers: { Authorization: `Bearer ${token}` } })
}

export function createComponent(token, component) {
  return request('/api/v1/components', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(component),
  })
}

export function updateComponent(token, componentId, payload) {
  return request(`/api/v1/components/${componentId}`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  })
}

export function completeComponentService(token, componentId, odometerKm) {
  return request(`/api/v1/components/${componentId}/service-complete?odometer_km=${odometerKm}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
}

export function getMaintenancePlans(token) {
  return request('/api/v1/maintenance-plans', { headers: { Authorization: `Bearer ${token}` } })
}

export function createMaintenancePlan(token, plan) {
  return request('/api/v1/maintenance-plans', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(plan),
  })
}

export function getParts(token) {
  return request('/api/v1/parts', { headers: { Authorization: `Bearer ${token}` } })
}

export function createPart(token, part) {
  return request('/api/v1/parts', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(part),
  })
}

export function createInventoryTransaction(token, transaction) {
  return request('/api/v1/inventory/transactions', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(transaction),
  })
}

export function getStockLocations(token) {
  return request('/api/v1/stock-locations', { headers: { Authorization: `Bearer ${token}` } })
}

export function createStockLocation(token, location) {
  return request('/api/v1/stock-locations', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(location),
  })
}

export function createInventoryMovement(token, movement) {
  return request('/api/v1/inventory/movements', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(movement),
  })
}

export function getExpenses(token) {
  return request('/api/v1/expenses', { headers: { Authorization: `Bearer ${token}` } })
}

export function createExpense(token, expense) {
  return request('/api/v1/expenses', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(expense),
  })
}

export function updateExpense(token, expenseId, payload) {
  return request(`/api/v1/expenses/${expenseId}`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  })
}

export function createFuelTransaction(token, payload) {
  return request('/api/v1/fuel-transactions', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  })
}

export function createTollTransaction(token, payload) {
  return request('/api/v1/toll-transactions', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  })
}

export function getDocuments(token) {
  return request('/api/v1/documents', { headers: { Authorization: `Bearer ${token}` } })
}

export function createDocument(token, document) {
  return request('/api/v1/documents', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(document),
  })
}

export function updateDocument(token, documentId, document) {
  return request(`/api/v1/documents/${documentId}`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(document),
  })
}

export async function uploadDocumentFile(token, documentId, file) {
  const form = new FormData()
  form.append('file', file)
  const response = await fetch(`${API_BASE_URL}/api/v1/documents/${documentId}/file`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  })
  if (!response.ok) throw new Error(`Upload failed with status ${response.status}`)
  return response.json()
}

export function getVendors(token) {
  return request('/api/v1/vendors', { headers: { Authorization: `Bearer ${token}` } })
}

export function createVendor(token, vendor) {
  return request('/api/v1/vendors', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(vendor),
  })
}

export function getPurchaseOrders(token) {
  return request('/api/v1/purchase-orders', { headers: { Authorization: `Bearer ${token}` } })
}

export function createPurchaseOrder(token, payload) {
  return request('/api/v1/purchase-orders', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  })
}

export function updatePurchaseOrder(token, orderId, status) {
  return request(`/api/v1/purchase-orders/${orderId}`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ status }),
  })
}

export function getPurchaseOrderReceipts(token, orderId) {
  return request(`/api/v1/purchase-orders/${orderId}/receipts`, { headers: { Authorization: `Bearer ${token}` } })
}

export function receivePurchaseOrder(token, orderId, payload) {
  return request(`/api/v1/purchase-orders/${orderId}/receipts`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  })
}

export function downloadUrl(path) {
  return `${API_BASE_URL}${path}`
}

export async function downloadFile(token, path, filename) {
  const response = await fetch(downloadUrl(path), {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!response.ok) throw new Error(`Download failed with status ${response.status}`)
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

export function exportResource(token, resource) {
  return fetch(downloadUrl(`/api/v1/export/${resource}`), {
    headers: { Authorization: `Bearer ${token}` },
  }).then(async (response) => {
    if (!response.ok) throw new Error(`Export failed with status ${response.status}`)
    return response.blob()
  })
}

export async function importResource(token, resource, file) {
  const form = new FormData()
  form.append('file', file)
  const response = await fetch(`${API_BASE_URL}/api/v1/import/${resource}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  })
  if (!response.ok) throw new Error(`Import failed with status ${response.status}`)
  return response.json()
}

export function getAlerts(token) {
  return request('/api/v1/alerts', { headers: { Authorization: `Bearer ${token}` } })
}

export function getNotifications(token) {
  return request('/api/v1/notifications', { headers: { Authorization: `Bearer ${token}` } })
}

export function getTelematicsIntegrations(token) {
  return request('/api/v1/telematics/integrations', { headers: { Authorization: `Bearer ${token}` } })
}

export function getTelematicsHealth(token) {
  return request('/api/v1/telematics/health', { headers: { Authorization: `Bearer ${token}` } })
}

export function syncDueTelematics(token) {
  return request('/api/v1/telematics/sync-due', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
}

export function createTelematicsIntegration(token, payload) {
  return request('/api/v1/telematics/integrations', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  })
}

export function createTelematicsDevice(token, payload) {
  return request('/api/v1/telematics/devices', {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  })
}

export function updateTelematicsIntegration(token, integrationId, payload) {
  return request(`/api/v1/telematics/integrations/${integrationId}`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  })
}

export function deleteTelematicsIntegration(token, integrationId) {
  return request(`/api/v1/telematics/integrations/${integrationId}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  })
}

export function getTelematicsDevices(token) {
  return request('/api/v1/telematics/devices', { headers: { Authorization: `Bearer ${token}` } })
}

export function ingestTelemetry(token, deviceId, payload) {
  return request(`/api/v1/telematics/devices/${deviceId}/readings`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(payload),
  })
}

export function updateNotification(token, notificationId, status) {
  return request(`/api/v1/notifications/${notificationId}`, {
    method: 'PATCH',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ status }),
  })
}

export function resolveNotification(token, notificationId) {
  return request(`/api/v1/notifications/${notificationId}/resolve`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
}

export function getWorkOrderChecklist(token, workOrderId) {
  return request(`/api/v1/work-orders/${workOrderId}/checklist`, {
    headers: { Authorization: `Bearer ${token}` },
  })
}

export function updateWorkOrderChecklist(token, workOrderId, items) {
  return request(`/api/v1/work-orders/${workOrderId}/checklist`, {
    method: 'PUT',
    headers: { Authorization: `Bearer ${token}`, 'Idempotency-Key': crypto.randomUUID() },
    body: JSON.stringify({ items }),
  })
}

export function startWorkOrder(token, workOrderId) {
  return request(`/api/v1/work-orders/${workOrderId}/start`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Idempotency-Key': crypto.randomUUID() },
  })
}

export function completeWorkOrder(token, workOrderId) {
  return request(`/api/v1/work-orders/${workOrderId}/complete`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Idempotency-Key': crypto.randomUUID() },
  })
}

export function approveWorkOrder(token, workOrderId) {
  return request(`/api/v1/work-orders/${workOrderId}/approve`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Idempotency-Key': crypto.randomUUID() },
  })
}

export function archiveWorkOrder(token, workOrderId) {
  return request(`/api/v1/work-orders/${workOrderId}/archive`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Idempotency-Key': crypto.randomUUID() },
  })
}

export function getWorkOrderParts(token, workOrderId) {
  return request(`/api/v1/work-orders/${workOrderId}/parts`, {
    headers: { Authorization: `Bearer ${token}` },
  })
}

export function getWorkOrderTimeline(token, workOrderId) {
  return request(`/api/v1/work-orders/${workOrderId}/timeline`, {
    headers: { Authorization: `Bearer ${token}` },
  })
}

export function recordWorkOrderPart(token, workOrderId, payload) {
  return request(`/api/v1/work-orders/${workOrderId}/parts`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Idempotency-Key': crypto.randomUUID() },
    body: JSON.stringify(payload),
  })
}

export function getWorkOrderEvidence(token, workOrderId) {
  return request(`/api/v1/work-orders/${workOrderId}/evidence`, {
    headers: { Authorization: `Bearer ${token}` },
  })
}

export async function uploadWorkOrderEvidence(token, workOrderId, file) {
  const form = new FormData()
  form.append('file', file)
  const response = await fetch(`${API_BASE_URL}/api/v1/work-orders/${workOrderId}/evidence`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: form,
  })
  if (!response.ok) throw new Error(`Evidence upload failed with status ${response.status}`)
  return response.json()
}

export function getDriverInspections(token) {
  return request('/api/v1/driver/inspections', { headers: { Authorization: `Bearer ${token}` } })
}

export async function createDriverInspection(token, payload) {
  if (!navigator.onLine) {
    queueOfflineMutation('/api/v1/driver/inspections', token, payload)
    return { queued: true }
  }
  try {
    return await request('/api/v1/driver/inspections', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify(payload),
    })
  } catch (error) {
    if (error instanceof TypeError) {
      queueOfflineMutation('/api/v1/driver/inspections', token, payload)
      return { queued: true }
    }
    throw error
  }
}

export async function createDriverIssue(token, payload) {
  if (!navigator.onLine) {
    queueOfflineMutation('/api/v1/driver/issues', token, payload)
    return { queued: true }
  }
  try {
    return await request('/api/v1/driver/issues', {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify(payload),
    })
  } catch (error) {
    if (error instanceof TypeError) {
      queueOfflineMutation('/api/v1/driver/issues', token, payload)
      return { queued: true }
    }
    throw error
  }
}

export function getDriverIssues(token) {
  return request('/api/v1/driver/issues', { headers: { Authorization: `Bearer ${token}` } })
}

export function reconcileExpense(token, expenseId) {
  return request(`/api/v1/expenses/${expenseId}/reconcile`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
}

export function reverseExpense(token, expenseId, reason) {
  return request(`/api/v1/expenses/${expenseId}/reverse`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify({ reason }),
  })
}
