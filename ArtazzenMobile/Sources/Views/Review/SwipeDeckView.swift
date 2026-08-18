import SwiftUI

struct SwipeDeckView: View {
    @State private var pending: [Artwork] = []
    @State private var offset: CGSize = .zero
    @State private var currentIndex = 0

    private let threshold: CGFloat = 120

    var body: some View {
        NavigationStack {
            ZStack {
                if pending.isEmpty {
                    ContentUnavailableView(
                        "No Pending Artwork",
                        systemImage: "checkmark.circle",
                        description: Text("All artwork has been reviewed.")
                    )
                } else {
                    ForEach(Array(pending.enumerated().reversed()), id: \.element.id) { index, artwork in
                        ReviewCard(artwork: artwork)
                            .offset(index == currentIndex ? offset : .zero)
                            .rotationEffect(.degrees(index == currentIndex ? Double(offset.width) / 20 : 0))
                            .scaleEffect(index == currentIndex ? 1.0 : 0.95)
                            .gesture(
                                index == currentIndex ?
                                DragGesture()
                                    .onChanged { value in
                                        offset = value.translation
                                    }
                                    .onEnded { value in
                                        if value.translation.width > threshold {
                                            approve()
                                        } else if value.translation.width < -threshold {
                                            hide()
                                        } else {
                                            withAnimation(.spring()) { offset = .zero }
                                        }
                                    }
                                : nil
                            )
                            .animation(.spring(), value: offset)
                    }

                    VStack {
                        Spacer()
                        HStack(spacing: 48) {
                            Button { hide() } label: {
                                Image(systemName: "xmark.circle.fill")
                                    .font(.system(size: 44))
                                    .foregroundStyle(Color.azOrange)
                            }
                            Button { approve() } label: {
                                Image(systemName: "checkmark.circle.fill")
                                    .font(.system(size: 44))
                                    .foregroundStyle(Color.azTeal)
                            }
                        }
                        .padding(.bottom, 32)
                    }
                }
            }
            .navigationTitle("Review")
        }
    }

    private func approve() {
        withAnimation(.easeOut(duration: 0.3)) {
            offset = CGSize(width: 500, height: 0)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            advanceCard()
        }
    }

    private func hide() {
        withAnimation(.easeOut(duration: 0.3)) {
            offset = CGSize(width: -500, height: 0)
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
            advanceCard()
        }
    }

    private func advanceCard() {
        guard currentIndex < pending.count - 1 else {
            pending.removeAll()
            return
        }
        currentIndex += 1
        offset = .zero
    }
}
