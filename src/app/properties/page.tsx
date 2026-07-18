import { redirect } from 'next/navigation'
import { createServerSupabaseClient } from '@/lib/supabaseServer'
import Link from 'next/link'

export default async function PropertiesPage() {
  const supabase = await createServerSupabaseClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/login')

  const { data: properties } = await supabase
    .from('properties')
    .select('*')
    .eq('status', 'active')
    .order('bid_date', { ascending: true })

  function formatPrice(price: number) {
    return (price / 100000000).toFixed(1) + '억'
  }

  function formatDate(dateStr: string) {
    const date = new Date(dateStr)
    return `${date.getMonth() + 1}월 ${date.getDate()}일`
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="bg-white px-5 py-4 flex items-center justify-between border-b border-gray-100">
        <h1 className="text-lg font-bold text-gray-900">콕찰 경매 매물</h1>
        <span className="text-xs text-gray-400">{user.email}</span>
      </div>
      <div className="px-4 py-4 space-y-3">
        {properties && properties.length > 0 ? (
          properties.map((property) => (
            <Link key={property.id} href={`/properties/${property.id}`}>
              <div className="bg-white rounded-2xl p-4 shadow-sm border border-gray-100 active:bg-gray-50 transition-all duration-200 mb-3">
                <div className="flex items-start justify-between mb-2">
                  <span className="text-xs font-medium text-blue-500 bg-blue-50 px-2 py-1 rounded-lg">
                    {property.property_type}
                  </span>
                  <span className="text-xs text-gray-400">{formatDate(property.bid_date)} 입찰</span>
                </div>
                <h2 className="text-base font-bold text-gray-900 mb-1">{property.title}</h2>
                <p className="text-sm text-gray-400 mb-3">{property.address}</p>
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-xs text-gray-400">감정가</p>
                    <p className="text-sm font-medium text-gray-700">{formatPrice(property.appraisal_price)}</p>
                  </div>
                  <div className="text-right">
                    <p className="text-xs text-gray-400">최저입찰가</p>
                    <p className="text-base font-bold text-blue-500">{formatPrice(property.minimum_bid_price)}</p>
                  </div>
                </div>
                <div className="mt-3 pt-3 border-t border-gray-50 flex items-center justify-between">
                  <span className="text-xs text-gray-400">{property.court_name}</span>
                  <span className="text-xs text-gray-400">{property.case_number}</span>
                </div>
              </div>
            </Link>
          ))
        ) : (
          <div className="text-center py-20">
            <p className="text-gray-400">등록된 매물이 없습니다</p>
          </div>
        )}
      </div>
    </div>
  )
}