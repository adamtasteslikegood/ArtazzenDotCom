import SwiftUI

struct QueueView: View {
    @State private var artworks: [Artwork] = []
    @State private var searchText = ""
    @State private var statusFilter: Artwork.ArtworkStatus? = .pending

    var filtered: [Artwork] {
        artworks.filter { art in
            if let filter = statusFilter, art.status != filter { return false }
            if searchText.isEmpty { return true }
            let q = searchText.lowercased()
            return art.title.lowercased().contains(q)
                || art.description.lowercased().contains(q)
                || art.tags.contains(where: { $0.lowercased().contains(q) })
        }
    }

    var body: some View {
        NavigationStack {
            List(filtered) { artwork in
                NavigationLink(value: artwork) {
                    QueueCard(artwork: artwork)
                }
            }
            .navigationTitle("Queue")
            .searchable(text: $searchText, prompt: "Search artwork")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button("All") { statusFilter = nil }
                        ForEach(Artwork.ArtworkStatus.allCases, id: \.self) { s in
                            Button(s.rawValue.capitalized) { statusFilter = s }
                        }
                    } label: {
                        Label("Filter", systemImage: "line.3.horizontal.decrease.circle")
                    }
                }
            }
            .navigationDestination(for: Artwork.self) { artwork in
                ArtworkDetailView(artwork: artwork)
            }
        }
    }
}
