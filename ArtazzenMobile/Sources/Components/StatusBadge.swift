import SwiftUI

struct StatusBadge: View {
    let status: Artwork.ArtworkStatus

    private var color: Color {
        switch status {
        case .approved: .azTeal
        case .pending: .azOrange
        case .hidden: .azCarbon.opacity(0.5)
        }
    }

    var body: some View {
        Text(status.rawValue.uppercased())
            .font(.system(size: 10, weight: .bold, design: .monospaced))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(color.opacity(0.15))
            .foregroundStyle(color)
            .clipShape(RoundedRectangle(cornerRadius: 3))
    }
}
