import SwiftUI

struct TagPill: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.azMono)
            .padding(.horizontal, 8)
            .padding(.vertical, 3)
            .background(Color.azCarbon.opacity(0.05))
            .clipShape(Capsule())
            .overlay(Capsule().stroke(Color.azCarbon.opacity(0.1), lineWidth: 1))
    }
}
