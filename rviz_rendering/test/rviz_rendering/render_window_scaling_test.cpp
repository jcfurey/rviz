// Copyright (c) 2026, John C. Furey
// All rights reserved.
//
// Redistribution and use in source and binary forms, with or without
// modification, are permitted provided that the following conditions are met:
//
//    * Redistributions of source code must retain the above copyright
//      notice, this list of conditions and the following disclaimer.
//
//    * Redistributions in binary form must reproduce the above copyright
//      notice, this list of conditions and the following disclaimer in the
//      documentation and/or other materials provided with the distribution.
//
//    * Neither the name of the copyright holder nor the names of its
//      contributors may be used to endorse or promote products derived from
//      this software without specific prior written permission.
//
// THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
// AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
// IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
// ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
// LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
// CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
// SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
// INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
// CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
// ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
// POSSIBILITY OF SUCH DAMAGE.


#include <gmock/gmock.h>

#include <QApplication>  // NOLINT
#include <QTest>  // NOLINT
#include <OgreViewport.h>  // NOLINT

#include "rviz_rendering/render_window.hpp"
#include "ogre_testing_environment.hpp"

TEST(RenderWindowScaling, viewport_matches_native_size_after_resizing)
{
  rviz_rendering::OgreTestingEnvironment environment;
  environment.setUpOgreTestEnvironment();
  rviz_rendering::RenderWindow window;
  window.resize(321, 243);
  window.show();
  ASSERT_TRUE(QTest::qWaitForWindowExposed(&window));

  for (const auto & size : {QSize(321, 243), QSize(503, 301), QSize(257, 199)}) {
    window.resize(size);
    QTest::qWait(50);
    window.renderNow();
    const auto * viewport = rviz_rendering::RenderWindowOgreAdapter::getOgreViewport(&window);
    ASSERT_NE(viewport, nullptr);
    EXPECT_EQ(window.size(), size);
    const auto native_size = size * window.devicePixelRatio();
    EXPECT_EQ(viewport->getActualWidth(), native_size.width());
    EXPECT_EQ(viewport->getActualHeight(), native_size.height());
  }
}

int main(int argc, char ** argv)
{
  QApplication app(argc, argv);
  testing::InitGoogleMock(&argc, argv);
  return RUN_ALL_TESTS();
}
